import motor.motor_asyncio
from datetime import datetime

class Database:
    def __init__(self, db_url, db_name):
        self.client = motor.motor_asyncio.AsyncIOMotorClient(db_url)
        self.db = self.client[db_name]

    async def add_document(self, document, collection_name="scraper_data"):
        collection = self.db[collection_name]
        await collection.insert_one(document)

    async def find_documents(self, query={}, collection_name="scraper_data"):
        collection = self.db[collection_name]
        return await collection.find(query).to_list(length=100)

    async def get_last_documents(self, count, collection_name="scraper_data"):
        collection = self.db[collection_name]
        return await collection.find().sort("added_on", -1).limit(count).to_list(length=count)
