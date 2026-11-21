import concurrent.futures as cf
from concurrent.futures import Future


class SyncExecutor:
    def __init__(self, max_workers=None, mp_context=None, initializer=None, initargs=(), **kw):
        if initializer:
            initializer(*initargs)

    def submit(self, fn, *a, **kw):
        f = Future()
        try:
            f.set_result(fn(*a, **kw))
        except BaseException as e:
            f.set_exception(e)
        return f

    def map(self, fn, *its, **kw):
        return (fn(*a) for a in zip(*its))

    def shutdown(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


cf.ProcessPoolExecutor = SyncExecutor
