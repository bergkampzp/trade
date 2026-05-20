from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException

from freqtrade.constants import Config
from freqtrade.enums import RunMode
from freqtrade.persistence import Trade
from freqtrade.persistence.models import _request_id_ctx_var
from freqtrade.rpc.api_server.webserver_bgwork import ApiBG
from freqtrade.rpc.rpc import RPC, RPCException

from .webserver import ApiServer


def get_rpc_optional() -> RPC | None:
    if ApiServer._has_rpc:
        return ApiServer._rpc
    return None


async def get_rpc() -> AsyncIterator[RPC] | None:
    _rpc = get_rpc_optional()
    if _rpc:
        request_id = str(uuid4())
        ctx_token = _request_id_ctx_var.set(request_id)
        Trade.rollback()
        try:
            yield _rpc
        finally:
            Trade.session.remove()
            _request_id_ctx_var.reset(ctx_token)

    else:
        raise RPCException("Bot is not in the correct state")


def get_config() -> dict[str, Any]:
    return ApiServer._config


def get_api_config() -> dict[str, Any]:
    return ApiServer._config["api_server"]


def _generate_exchange_key(config: Config) -> str:
    """
    Exchange key - used for caching the exchange object.
    """
    return f"{config['exchange']['name']}_{config.get('trading_mode', 'spot')}"


def get_exchange(config=Depends(get_config)):
    exchange_key = _generate_exchange_key(config)
    if not (exchange := ApiBG.exchanges.get(exchange_key)):
        from freqtrade.resolvers import ExchangeResolver

        exchange = ExchangeResolver.load_exchange(config, validate=False, load_leverage_tiers=False)
        ApiBG.exchanges[exchange_key] = exchange
    return exchange


def get_message_stream():
    return ApiServer._message_stream


def is_webserver_mode(config=Depends(get_config)):
    if config["runmode"] != RunMode.WEBSERVER:
        raise HTTPException(status_code=503, detail="Bot is not in the correct state.")
    return None


_quant_db_instance = None


def get_quant_db(config=Depends(get_config)):
    """Lazily create and cache a QuantDB connection pool."""
    global _quant_db_instance  # noqa: PLW0603
    quant_cfg = config.get("quant_db", {})
    dsn = quant_cfg.get("dsn")
    if not dsn:
        return None
    if _quant_db_instance is None:
        from freqtrade.rpc.api_server.quant_db import QuantDB

        _quant_db_instance = QuantDB(dsn)
    return _quant_db_instance


def close_quant_db() -> None:
    """Close the QuantDB connection pool (call on server shutdown)."""
    global _quant_db_instance  # noqa: PLW0603
    if _quant_db_instance is not None:
        _quant_db_instance.close()
        _quant_db_instance = None
