from telebot.handler_backends import BaseMiddleware


def no_op_middleware_hook(*_) -> None:
    return None


class NoOpPreProcessMiddleware(BaseMiddleware):
    pre_process = no_op_middleware_hook


class NoOpPostProcessMiddleware(BaseMiddleware):
    post_process = no_op_middleware_hook
