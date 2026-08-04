"""
MongoDB connection setup.

Client creation is lazy by design (pymongo doesn't actually open a socket
until the first operation), matching how the rest of the app doesn't
eagerly touch external state at startup either. Routes that use the DB
are responsible for catching pymongo.errors.PyMongoError and returning a
JSON error - same "always return valid JSON" contract already used for
the PQPR search endpoints - rather than the app crashing if Mongo isn't
running yet.
"""

from pymongo import MongoClient


def init_mongo(app, settings):
    """Create the Mongo client + database handle and stash them on the
    Flask app config, so routes can pull app.config["MONGO_DB"]."""
    uri = settings["secrets"]["mongo_uri"]
    db_name = settings["mongodb"]["db_name"]

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    app.config["MONGO_CLIENT"] = client
    app.config["MONGO_DB"] = client[db_name]
