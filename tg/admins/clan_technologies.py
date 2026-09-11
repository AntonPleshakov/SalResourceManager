from html import escape

from telebot import TeleBot, formatting
from telebot.apihelper import ApiTelegramException
from telebot.handler_backends import State, StatesGroup
from telebot.types import InlineKeyboardMarkup

from db.initializer import get_access_group_db, get_user_data_db
from logger.app_logger import logger
from resources.clan_technology_calculator import (
    rank_clan_technology_upgrades,
)
from resources.clan_technologies import (
    CLAN_TECHNOLOGY_BY_NAME,
    CLAN_TECHNOLOGY_DEFINITIONS,
    validate_clan_technology_level,
)
from resources.war import WAR_STAGES
from tg.handlers import (
    ActiveClan,
    ClanAdminContext,
    ClanFromState,
    HandlerRegistry,
)
from tg.rich import (
    details,
    edit_rich_message,
    footer,
    heading,
    input_rich_message,
)
from tg.utils import Button, format_points, get_ids, get_username


TECHNOLOGIES_PER_ROW = 4
SCORING_TECHNOLOGIES = tuple(
    definition
    for definition in CLAN_TECHNOLOGY_DEFINITIONS
    if definition.affects_war_points
)
TECHNOLOGY_GRID_TITLES = {
    "forging_equipment": "Ковка",
    "summoning_skills": "Призыв",
    "upgrading_skills": "Навык+",
    "tech_tree": "Древо",
    "forge_upgrades": "Кузня",
    "dungeon_keys": "Ключи",
    "hatching_eggs": "Яйца",
    "merging_pets": "Петы+",
    "summoning_mounts": "Маунты",
    "merging_mounts": "Маунт+",
    "clan_war_day_1": "День1",
    "clan_war_day_2": "День2",
    "clan_war_day_3": "День3",
    "clan_war_day_4": "День4",
    "clan_war_day_5": "День5",
    "clan_war_day_6": "День6",
}


class ClanTechnologyStates(StatesGroup):
    level = State()


def _level_keyboard(definition) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        Button("✖️ Отмена", "admins/clan_technologies").inline(),
        Button(
            "⬆️ Максимальный уровень",
            f"admins/clan_technologies/max/{definition.name}",
        ).inline(),
    )
    return keyboard


def _technology_level_label(definition, technologies) -> str:
    level = getattr(technologies, definition.name)
    return (
        "Max"
        if level == definition.max_level
        else f"{level} / {definition.max_level}"
    )


def _technology_keyboard(technologies) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=TECHNOLOGIES_PER_ROW)
    for index in range(0, len(SCORING_TECHNOLOGIES), TECHNOLOGIES_PER_ROW):
        definitions = SCORING_TECHNOLOGIES[
            index : index + TECHNOLOGIES_PER_ROW
        ]
        keyboard.row(
            *(
                Button(
                    f"{definition.icon} "
                    f"{_technology_level_label(definition, technologies)}",
                    f"admins/clan_technologies/edit/{definition.name}",
                ).inline()
                for definition in definitions
            )
        )
    keyboard.row(
        Button(
            "🧮 Что качать?",
            "admins/clan_technologies/calculator",
        ).inline()
    )
    keyboard.row(
        Button("⬅️ Админ-панель", "admins").inline(),
        Button("🏠 Главное меню", "home").inline(),
    )
    return keyboard


def _technology_calculator_message(group, users, technologies):
    recommendations = rank_clan_technology_upgrades(
        users,
        technologies,
        WAR_STAGES,
    )
    parts = [
        heading("Калькулятор клановых технологий"),
        footer(f"Клан: {group.title}"),
    ]
    if not users:
        parts.append(
            "<blockquote>В клане пока нет аккаунтов с игровыми "
            "данными. Добавьте аккаунты, чтобы сравнить улучшения."
            "</blockquote>"
        )
    elif not recommendations:
        parts.append(
            "<blockquote>Все технологии, влияющие на очки войны, "
            "уже улучшены до максимума.</blockquote>"
        )
    else:
        best = recommendations[0]
        parts.extend(
            (
                "<aside>Выгоднее всего сейчас<br>"
                f"<b>{escape(best.definition.icon)} "
                f"{escape(best.definition.title)} → "
                f"уровень {best.next_level}</b><br>"
                f"+{format_points(best.points_gain)} очков за "
                f"{best.definition.flask_cost} колб</aside>",
                '<table bordered compact><caption>Рейтинг улучшений</caption>',
                "<tr><th>Технология</th><th>Очков/колбу</th>"
                "<th>За 1 уровень</th><th>До Max</th></tr>",
                *(
                    "<tr>"
                    f"<td>{escape(recommendation.definition.icon)} "
                    f"{escape(recommendation.definition.title)}</td>"
                    f"<td><b>"
                    f"{format_points(recommendation.points_per_flask)}"
                    "/🧪</b></td>"
                    f"<td>+{format_points(recommendation.points_gain)}</td>"
                    f"<td>+{format_points(recommendation.max_points_gain)}<br>"
                    f"{recommendation.levels_to_max} ур. · "
                    f"{recommendation.flasks_to_max} 🧪</td>"
                    "</tr>"
                    for recommendation in recommendations
                ),
                "</table>",
                details(
                    "Как считается рейтинг",
                    "<p>Для каждой доступной технологии калькулятор "
                    "повышает уровень на один и пересчитывает итоговые "
                    "очки войны. Рейтинг отсортирован по приросту очков "
                    "на одну потраченную колбу. Рядом показан прирост "
                    "за один уровень и суммарный прирост до Max.</p>"
                    "<p>Используются последние сохранённые данные всех "
                    f"аккаунтов клана ({len(users)}) и текущее расписание "
                    "войны. Боевые бонусы и награды не входят в рейтинг, "
                    "поскольку они не увеличивают очки.</p>",
                ),
            )
        )
    parts.append(
        '<hr><tg-button-row>'
        '<tg-button type="callback_data" '
        'data="admins/clan_technologies">⬅️ Технологии</tg-button>'
        '<tg-button type="callback_data" data="home">'
        "🏠 Главное меню</tg-button></tg-button-row>"
    )
    return input_rich_message(parts)


def _technology_cells(values) -> str:
    cells = tuple(values)
    return "".join(
        f'<td align="center">{value}</td>' for value in cells
    ) + '<td colspan="1"></td>' * (TECHNOLOGIES_PER_ROW - len(cells))


def _technology_grid(technologies) -> str:
    rows = ["<table compact>"]
    for index in range(0, len(SCORING_TECHNOLOGIES), TECHNOLOGIES_PER_ROW):
        definitions = SCORING_TECHNOLOGIES[
            index : index + TECHNOLOGIES_PER_ROW
        ]
        icon_cells = _technology_cells(
            escape(definition.icon) for definition in definitions
        )
        title_cells = _technology_cells(
            escape(TECHNOLOGY_GRID_TITLES[definition.name])
            for definition in definitions
        )
        level_cells = _technology_cells(
            escape(_technology_level_label(definition, technologies))
            for definition in definitions
        )
        rows.extend(
            (
                f"<tr>{icon_cells}</tr>",
                f"<tr>{title_cells}</tr>",
                f"<tr>{level_cells}</tr>",
            )
        )
    rows.append("</table>")
    return "".join(rows)


def _clan_technologies_message(group, technologies, notice: str = ""):
    notice_part = (
        f"<blockquote>{escape(notice)}</blockquote>" if notice else ""
    )
    return input_rich_message(
        (
            heading("Клановые технологии"),
            footer(f"Клан: {group.title}"),
            details(
                "Справка",
                "<p>Таблица соответствует таблице «Clan War» из игры, "
                "но без технологий на урон и других технологий, которые "
                "не влияют на очки войны.</p>"
                "<p>Чтобы изменить технологию, нажмите кнопку с её "
                "текущим уровнем.</p>",
            ),
            notice_part,
            _technology_grid(technologies),
        )
    )


def _show_clan_technologies(
    bot, chat_id: int, message_id: int, group, notice: str = ""
) -> None:
    technologies = get_access_group_db().get_clan_technologies(
        group.group_id
    )
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        _clan_technologies_message(group, technologies, notice),
        reply_markup=_technology_keyboard(technologies),
    )


def clan_technologies_menu(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    _, chat_id, message_id = get_ids(callback_query)
    bot.delete_state(callback_query.from_user.id)
    _show_clan_technologies(
        bot, chat_id, message_id, context.group
    )


def clan_technology_calculator(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    _, chat_id, message_id = get_ids(callback_query)
    technologies = get_access_group_db().get_clan_technologies(
        context.group.group_id
    )
    users = get_user_data_db().get_clan_users(context.group.group_id)
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        _technology_calculator_message(
            context.group,
            users,
            technologies,
        ),
    )


def _show_level_prompt(
    bot,
    chat_id: int,
    message_id: int,
    group,
    definition,
    current_level: int,
    error: str = "",
) -> None:
    error_text = (
        f"\n\n⚠️ {formatting.escape_html(error)}." if error else ""
    )
    bot.edit_message_text(
        f"<b>{formatting.escape_html(definition.title)}</b>\n\n"
        f"Клан: <b>{formatting.escape_html(group.title)}</b>\n"
        f"Текущий уровень: <b>{current_level}</b>\n"
        f"Максимальный уровень: <b>{definition.max_level}</b>\n"
        f"Прирост за уровень: <b>{definition.increase_percent}%</b>\n"
        f"Стоимость уровня: <b>{definition.flask_cost} колб</b>"
        f"{error_text}\n\n"
        "Отправьте новый уровень.",
        chat_id,
        message_id,
        reply_markup=_level_keyboard(definition),
    )


def request_clan_technology_level(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    name = callback_query.data.rsplit("/", maxsplit=1)[-1]
    definition = CLAN_TECHNOLOGY_BY_NAME.get(name)
    if definition is None:
        bot.answer_callback_query(
            callback_query.id, "Технология не найдена", show_alert=True
        )
        return
    technologies = get_access_group_db().get_clan_technologies(
        context.group.group_id
    )
    user_id, chat_id, message_id = get_ids(callback_query)
    bot.set_state(user_id, ClanTechnologyStates.level)
    bot.add_data(
        user_id,
        clan_technology_group_id=context.group.group_id,
        clan_technology_name=name,
        clan_technology_prompt_message_id=message_id,
    )
    _show_level_prompt(
        bot,
        chat_id,
        message_id,
        context.group,
        definition,
        getattr(technologies, name),
    )


def _parse_level(name: str, text: str) -> int:
    normalized = (text or "").strip()
    if not normalized.isdigit():
        raise ValueError("Введите целое неотрицательное число")
    return validate_clan_technology_level(name, int(normalized))


def _delete_level_message(message, bot) -> None:
    _, chat_id, message_id = get_ids(message)
    try:
        bot.delete_message(chat_id, message_id)
    except ApiTelegramException as error:
        logger.warning(
            "Unable to delete clan technology input chat_id=%s "
            "message_id=%s reason=%s",
            chat_id,
            message_id,
            error,
        )


def set_max_clan_technology_level(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    name = callback_query.data.rsplit("/", maxsplit=1)[-1]
    with bot.retrieve_data(user_id) as data:
        expected_name = data.get("clan_technology_name")
    definition = CLAN_TECHNOLOGY_BY_NAME.get(name)
    if definition is None or name != expected_name:
        bot.answer_callback_query(
            callback_query.id, "Технология не найдена", show_alert=True
        )
        return
    get_access_group_db().set_clan_technology(
        context.group.group_id, name, definition.max_level
    )
    bot.delete_state(user_id)
    logger.info(
        "Clan technology set to maximum by admin user_id=%s username=%s "
        "group_id=%s technology=%s level=%s",
        user_id,
        get_username(callback_query),
        context.group.group_id,
        name,
        definition.max_level,
    )
    _show_clan_technologies(
        bot,
        chat_id,
        message_id,
        context.group,
        f"{definition.title}: уровень Max — сохранено.",
    )


def save_clan_technology_level(context: ClanAdminContext) -> None:
    message = context.update
    bot = context.bot
    user_id, chat_id = get_ids(message)[:2]
    with bot.retrieve_data(user_id) as data:
        name = data.get("clan_technology_name")
        prompt_message_id = data.get("clan_technology_prompt_message_id")
    definition = CLAN_TECHNOLOGY_BY_NAME.get(name)
    _delete_level_message(message, bot)
    if definition is None or not isinstance(prompt_message_id, int):
        bot.delete_state(user_id)
        bot.send_message(chat_id, "Не удалось определить технологию.")
        return
    try:
        level = _parse_level(name, message.text)
    except ValueError as error:
        technologies = get_access_group_db().get_clan_technologies(
            context.group.group_id
        )
        _show_level_prompt(
            bot,
            chat_id,
            prompt_message_id,
            context.group,
            definition,
            getattr(technologies, name),
            str(error),
        )
        return
    get_access_group_db().set_clan_technology(
        context.group.group_id, name, level
    )
    bot.delete_state(user_id)
    logger.info(
        "Clan technology updated by admin user_id=%s username=%s "
        "group_id=%s technology=%s level=%s",
        user_id,
        get_username(message),
        context.group.group_id,
        name,
        level,
    )
    _show_clan_technologies(
        bot,
        chat_id,
        prompt_message_id,
        context.group,
        f"{definition.title}: уровень {level} — сохранено.",
    )


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering clan-technology handlers")
    handlers = HandlerRegistry(bot)
    handlers.clan_admin_callback(
        clan_technologies_menu,
        button="admins/clan_technologies",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        clan_technology_calculator,
        button="admins/clan_technologies/calculator",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        request_clan_technology_level,
        button=r"admins/clan_technologies/edit/[a-z0-9_]+",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        set_max_clan_technology_level,
        button=r"admins/clan_technologies/max/[a-z0-9_]+",
        clan=ClanFromState("clan_technology_group_id"),
    )
    handlers.clan_admin_message(
        save_clan_technology_level,
        content_types=["text"],
        state=ClanTechnologyStates.level,
        clan=ClanFromState("clan_technology_group_id"),
    )
