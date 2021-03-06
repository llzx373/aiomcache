import asyncio
from collections import namedtuple

__all__ = ['MemcachePool']


_connection = namedtuple('connection', ['reader', 'writer'])


class MemcachePool:

    def __init__(self, host, port, *, minsize, maxsize, loop=None):
        loop = loop if loop is not None else asyncio.get_event_loop()
        self._host = host
        self._port = port
        self._minsize = minsize
        self._loop = loop
        self._pool = asyncio.Queue(maxsize, loop=loop)
        self._in_use = set()

    @asyncio.coroutine
    def clear(self):
        """Clear pool connections."""
        while not self._pool.empty():
            conn = yield from self._pool.get()
            self._do_close(conn)

    def _do_close(self, conn):
        conn.reader.feed_eof()
        conn.writer.close()

    @asyncio.coroutine
    def acquire(self):
        """Acquire connection from the pool, or spawn new one
        if pool maxsize permits.

        :return: ``tuple`` (reader, writer)
        """
        while self.size() < self._minsize:
            _conn = yield from self._create_new_conn()
            yield from self._pool.put(_conn)

        conn = None
        while not conn:
            if not self._pool.empty():
                _conn = yield from self._pool.get()
                if _conn.reader.at_eof() or _conn.reader.exception():
                    self._do_close(_conn)
                    conn = None

            if conn is None:
                conn = yield from self._create_new_conn()

        self._in_use.add(conn)
        return conn

    def release(self, conn):
        """Releases connection back to the pool.

        :param conn: ``namedtuple`` (reader, writer)
        """
        self._in_use.remove(conn)

        if conn.reader.at_eof() or conn.reader.exception():
            self._do_close(conn)
        else:
            try:
                self._pool.put_nowait(conn)
            except asyncio.QueueFull:
                self._do_close(conn)

    @asyncio.coroutine
    def _create_new_conn(self):
        reader, writer = yield from asyncio.open_connection(
            self._host, self._port, loop=self._loop)
        return _connection(reader, writer)

    def size(self):
        return len(self._in_use) + self._pool.qsize()
