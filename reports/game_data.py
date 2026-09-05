"""Export the current user-data snapshot to Google Sheets."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Iterable
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
import pygsheets
from pygsheets.client import Client
from pygsheets.exceptions import WorksheetNotFound

from common.datetime_utils import format_last_update
from config.config import getconf
from db.access_group import AccessGroupDB
from db.initializer import get_access_group_db
from logger.app_logger import logger
from resources.user_data import UPDATED_AT_FIELDS, UserData


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOOGLE_SERVICE_FILE = _PROJECT_ROOT / "gapi_service_file.json"
USER_DATA_PAGE_NAME = "User data"
_TRACKED_FIELD_BY_UPDATE_FIELD = {
    update_field: tracked_field
    for tracked_field, update_field in UPDATED_AT_FIELDS.items()
}
_DRIVE_API_BASE_URL = "https://www.googleapis.com/drive/v3/files"
_GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_GOOGLE_SPREADSHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


@dataclass(frozen=True)
class GoogleAccessProposal:
    proposal_id: str
    email: str


class GameDataReport:
    HEADER = [UserData().params_views()]
    _creation_locks: dict[int, Lock] = {}
    _creation_locks_guard = Lock()

    def __init__(
        self,
        client: Client = None,
        groups: AccessGroupDB = None,
        drive_session: AuthorizedSession = None,
    ):
        self._client = client
        self._groups = groups
        self._drive = drive_session
        self._report_folder_id = None

    def _google_client(self) -> Client:
        if self._client is None:
            self._client = pygsheets.authorize(
                service_file=str(GOOGLE_SERVICE_FILE)
            )
        return self._client

    def _group_database(self) -> AccessGroupDB:
        return self._groups or get_access_group_db()

    def _drive_session(self) -> AuthorizedSession:
        if self._drive is None:
            self._drive = AuthorizedSession(self._google_client().oauth)
        return self._drive

    @classmethod
    def _creation_lock(cls, group_id: int) -> Lock:
        with cls._creation_locks_guard:
            return cls._creation_locks.setdefault(int(group_id), Lock())

    def _shared_drive_folder_id(self) -> str:
        if self._report_folder_id is not None:
            return self._report_folder_id

        folder_id = getconf("GAME_DATA_GFOLDER_KEY")
        folder_response = self._drive_session().get(
            f"{_DRIVE_API_BASE_URL}/{quote(folder_id, safe='')}",
            params={
                "fields": "mimeType,driveId,capabilities(canAddChildren)",
                "supportsAllDrives": "true",
            },
            timeout=10,
        )
        folder_response.raise_for_status()
        folder = folder_response.json()
        if folder.get("mimeType") != _GOOGLE_FOLDER_MIME_TYPE:
            raise RuntimeError(
                "GAME_DATA_GFOLDER_KEY does not point to a Google Drive folder"
            )
        if not folder.get("driveId"):
            raise RuntimeError(
                "GAME_DATA_GFOLDER_KEY must point to a Shared Drive folder; "
                "service accounts cannot own files"
            )
        if not folder.get("capabilities", {}).get("canAddChildren"):
            raise PermissionError(
                "The Google service account cannot add files to the configured "
                "Shared Drive folder"
            )

        self._google_client().drive.enable_team_drive(folder["driveId"])
        self._report_folder_id = folder_id
        return folder_id

    def _create_spreadsheet(self, title: str):
        folder_id = self._shared_drive_folder_id()
        create_response = self._drive_session().post(
            _DRIVE_API_BASE_URL,
            params={"fields": "id", "supportsAllDrives": "true"},
            json={
                "name": title,
                "mimeType": _GOOGLE_SPREADSHEET_MIME_TYPE,
                "parents": [folder_id],
            },
            timeout=10,
        )
        create_response.raise_for_status()
        return self._google_client().open_by_key(create_response.json()["id"])

    def _open_or_create_spreadsheet(self, group_id: int, clan_title: str):
        groups = self._group_database()
        client = self._google_client()
        self._shared_drive_folder_id()
        spreadsheet_id = groups.get_spreadsheet_id(group_id)
        if spreadsheet_id is not None:
            return client.open_by_key(spreadsheet_id)

        with self._creation_lock(group_id):
            spreadsheet_id = groups.get_spreadsheet_id(group_id)
            if spreadsheet_id is not None:
                return client.open_by_key(spreadsheet_id)
            spreadsheet = self._create_spreadsheet(
                f"Forge Master — {clan_title}"
            )
            groups.set_spreadsheet_id(group_id, spreadsheet.id)
            logger.info(
                "Created clan Google spreadsheet group_id=%s spreadsheet_id=%s",
                group_id,
                spreadsheet.id,
            )
            return spreadsheet

    def prepare(self, group_id: int, clan_title: str) -> str:
        return self._open_or_create_spreadsheet(group_id, clan_title).url

    def get_access_proposals(
        self,
        group_id: int,
        created_after: int,
    ) -> list[GoogleAccessProposal]:
        spreadsheet_id = self._group_database().get_spreadsheet_id(group_id)
        if spreadsheet_id is None:
            raise ValueError("Для клана ещё не создана Google Таблица")
        endpoint = (
            f"{_DRIVE_API_BASE_URL}/{quote(spreadsheet_id, safe='')}"
            "/accessproposals"
        )
        proposals = []
        page_token = None
        while True:
            parameters = {
                "fields": (
                    "nextPageToken,accessProposals("
                    "proposalId,requesterEmailAddress,"
                    "recipientEmailAddress,createTime)"
                ),
                "pageSize": 100,
            }
            if page_token is not None:
                parameters["pageToken"] = page_token
            response = self._drive_session().get(
                endpoint,
                params=parameters,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            for proposal in payload.get("accessProposals", []):
                requester = str(
                    proposal.get("requesterEmailAddress", "")
                ).strip().casefold()
                recipient = str(
                    proposal.get("recipientEmailAddress", requester)
                ).strip().casefold()
                created_at = datetime.fromisoformat(
                    str(proposal["createTime"]).replace("Z", "+00:00")
                ).timestamp()
                if (
                    requester
                    and recipient == requester
                    and created_at >= int(created_after)
                ):
                    proposals.append(
                        GoogleAccessProposal(
                            str(proposal["proposalId"]),
                            requester,
                        )
                    )
            page_token = payload.get("nextPageToken")
            if not page_token:
                return proposals

    def approve_access(self, group_id: int, proposal_id: str) -> None:
        spreadsheet_id = self._group_database().get_spreadsheet_id(group_id)
        if spreadsheet_id is None:
            raise ValueError("Для клана ещё не создана Google Таблица")
        endpoint = (
            f"{_DRIVE_API_BASE_URL}/{quote(spreadsheet_id, safe='')}"
            f"/accessproposals/{quote(proposal_id, safe='')}:resolve"
        )
        response = self._drive_session().post(
            endpoint,
            json={
                "role": ["reader"],
                "action": "ACCEPT",
                "sendNotification": False,
            },
            timeout=10,
        )
        response.raise_for_status()

    @staticmethod
    def _grant_reader(spreadsheet, google_email: str) -> None:
        matching_permissions = [
            permission
            for permission in spreadsheet.permissions
            if str(permission.get("emailAddress", "")).casefold()
            == google_email.casefold()
        ]
        if len(matching_permissions) == 1 and (
            matching_permissions[0].get("type") == "user"
            and matching_permissions[0].get("role") == "reader"
        ):
            return
        for permission in matching_permissions:
            spreadsheet.remove_permission(
                google_email,
                permission_id=permission["id"],
            )
        spreadsheet.share(
            google_email,
            role="reader",
            type="user",
            sendNotificationEmail=False,
        )

    @staticmethod
    def _escape_formulas(row: list[str]) -> list[str]:
        return [
            f"'{value}" if value.startswith(("=", "+")) else value
            for value in row
        ]

    @staticmethod
    def _to_report_row(user: UserData) -> list[str]:
        row = user.to_row()
        for index, parameter_name in enumerate(user.params()):
            tracked_field = _TRACKED_FIELD_BY_UPDATE_FIELD.get(parameter_name)
            if tracked_field is None:
                continue
            updated_on = user.get_updated_on(tracked_field)
            row[index] = format_last_update(updated_on)
        return row

    @classmethod
    def build_rows(cls, users: Iterable[UserData]) -> list[list[str]]:
        return cls.HEADER + [cls._to_report_row(user) for user in users]

    def export(
        self,
        group_id: int,
        clan_title: str,
        google_email: str,
        users: Iterable[UserData],
    ) -> str:
        users = list(users)
        spreadsheet = self._open_or_create_spreadsheet(group_id, clan_title)
        self._grant_reader(spreadsheet, google_email)
        try:
            worksheet = spreadsheet.worksheet_by_title(USER_DATA_PAGE_NAME)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(USER_DATA_PAGE_NAME)

        report_rows = self.build_rows(users)
        rows = report_rows[:1] + [
            self._escape_formulas(row) for row in report_rows[1:]
        ]
        worksheet.clear()
        worksheet.update_values("A1", rows, extend=True)
        worksheet.show_dimensions(1, worksheet.cols, dimension="COLUMNS")
        worksheet.frozen_rows = len(self.HEADER)
        logger.info("Game data report exported: users=%d", len(users))
        return spreadsheet.url

    def revoke_access(self, group_id: int, google_email: str | None) -> None:
        if not google_email:
            return
        spreadsheet_id = self._group_database().get_spreadsheet_id(group_id)
        if spreadsheet_id is None:
            return
        self._shared_drive_folder_id()
        spreadsheet = self._google_client().open_by_key(spreadsheet_id)
        for permission in spreadsheet.permissions:
            if (
                str(permission.get("emailAddress", "")).casefold()
                == google_email.casefold()
            ):
                spreadsheet.remove_permission(
                    google_email,
                    permission_id=permission["id"],
                )
        logger.info(
            "Revoked clan Google spreadsheet access group_id=%s",
            group_id,
        )
