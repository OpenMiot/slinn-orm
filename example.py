from orm.sqlite import SQLite
from orm.models import Model, InetField
from ipaddress import IPv4Address
import asyncio


pool = SQLite('sqlite://./db.sqlite3')

class Ips(Model):
    @staticmethod
    def __collection_name__():
        return 'ips'
    
    ip = InetField()
    


async def main():
    async with await pool.acquire() as conn:
        await conn.create(Ips(), exists_ok=True)
        await conn.ips.insert({'ip': IPv4Address('127.0.0.1')})
        for ip in await conn.ips.find({}):
            print(ip)
    await pool.close()
    
if __name__ == '__main__':
    asyncio.run(main())
