"""Positive dependency evidence only: absence can never authorize cleanup."""
import json


class Dependencies:
    def __init__(self, store):
        self.store = store

    def records(self, server_uuid, parent_uuid):
        output = []
        for row in self.store.db.execute("SELECT id,payload,state FROM operations WHERE state != 'prepared'"):
            step = json.loads(row["payload"])
            dependency = step.get("binding", {}).get("parent_dependency")
            if not dependency or (dependency.get("server_uuid"), dependency.get("parent_uuid")) != (server_uuid, parent_uuid):
                continue
            observation = self.store.db.execute("SELECT observation FROM execution_steps WHERE operation_id=?", (row["id"],)).fetchone()
            if observation and observation[0] and json.loads(observation[0]).get("state") == "not_submitted":
                continue
            output.append({"operation_id": row["id"], "state": row["state"], "dependency": dependency})
        return output
