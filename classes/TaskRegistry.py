import asyncio

class TaskRegistry:
    """
    A static registry to manage task_id to Future mappings.
    """
    _registry = {}
    _lock = asyncio.Lock()  # Add a lock to synchronize access

    @classmethod
    async def add_task(cls, task_id, future):
        """Adds a Future to the registry."""
        async with cls._lock:
            print(f"Adding future {id(future)} to task {task_id} registry")
            if task_id in cls._registry:
                raise ValueError(f"Task with ID {task_id} already exists in the registry.")
            cls._registry[task_id] = future

    @classmethod
    async def get_task(cls, task_id):
        """Retrieves a Future from the registry."""
        async with cls._lock:
            future = cls._registry.get(task_id)
            print(f"Retrieving future {id(future)} task {task_id} registry")
            return future

    @classmethod
    async def remove_task(cls, task_id):
        """Removes a Future from the registry."""
        async with cls._lock:
            if task_id in cls._registry:
                del cls._registry[task_id]
