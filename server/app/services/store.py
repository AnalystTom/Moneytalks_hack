def put(store: dict, key: str, value, cap: int = 500) -> None:
    """Insert into an in-memory store, evicting the oldest entry beyond `cap`."""
    store[key] = value
    while len(store) > cap:
        store.pop(next(iter(store)))
