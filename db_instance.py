from database import Database
from configs import DATABASE_URL

# Single instance to use throughout the project
db = Database(DATABASE_URL, "MadxBotz_Scrapper")
