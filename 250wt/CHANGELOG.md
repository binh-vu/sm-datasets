# Changelog

Current version: **1.1.1**

### [1.1.1] 2021-12-14

---

- add wikipedia pages that contain the tables, each file contains a json object: `{"url": <url of the page>, "html": <content of the page>}`.
- add a file telling the version so that we don't need to open the changelog

### [1.1.0] 2021-11-04

---

- rename `links.*.*.qnode_id` to `links.*.*.entity_id`
- rename `context.page_qnode` to `context.page_entity_id`
- shorten `table_id` to remove `dbpedia.org/resource/` & url query parameters if possible
- pump version from "1" to "1.1"
- previous version **1.0.0** is saved to [v100.zip](./v100.zip)
