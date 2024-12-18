from payments_py import Payments
from payments_py.data_models import TaskLog, AgentExecutionStatus
from logger.logger import logger
from typing import Optional


async def log_message(payments: Payments, task_id: str, level: str, message: str, task_status: Optional[AgentExecutionStatus] = None) -> None:
    """
    Logs a message to the console and updates the log on the Nevermined platform.

    Args:
        payments (Payments): Instance of the Payments API for interacting with Nevermined.
        task_id (str): The ID of the task associated with the log message.
        level (str): The level of the log (e.g., "info", "warning", "error").
        message (str): The message to log.

    Returns:
        None
    """
    log_methods = {
        "info": logger.info,
        "warning": logger.warning,
        "error": logger.error,
        "debug": logger.debug
    }

    log_methods.get(level, logger.info)(f"{task_id} :: {message}")
    if task_status is None:
        task_log = TaskLog(task_id=task_id, level=level, message=message)
    else:
        task_log = TaskLog(task_id=task_id, level=level, message=message, task_status=task_status)
    await payments.ai_protocol.log_task(task_log)