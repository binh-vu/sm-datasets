# Changelog

Current version: **1.5.0**

### [1.5.0] 2024-04-12

- Add missing column types (for object properties) and missing entities for those columns

### [1.4.1] 2023-03-15

- Add missing part of to between tennis tournament edition and tennis with multiple editions in table 2018_angelique_kerber_tennis_season.

### [1.4.0] 2023-03-14

---

- Added linked entitiy corrections. We pre-filter low-chanced error tables using heuristics so the list may not be completed.
- 2016–17_Pro_A_season: inconsistent annotation, in some models, Stadium is modeled as sport venue (which is correct). In the other models, it is entity. Change it to sport value.
- College sport related tables: add models where college columns are annotated as college/school/university follow the column meaning instead of the existing linked entities (e.g., `1967_NFL/AFL_Draft`, `1992_Major_League_Baseball_draft`).
- Fix column types that are not specific enough (e.g., `FC_Nordsjælland_in_European_football` sport club to association football club, `Bluebird_Airways` change geographic feature to geographic region, Album related tables such as `List_of_2009_albums?ref=1.1_2` - change artist column from entity to agent)

### [1.3.0] 2022-04-27

---

- update sport related tables, if a stadium is a home venue of a club, the club also occupied the stadium.

### [1.2.0] 2021-12-29

---

- add additional semantic descriptions of tables that include the table subjects. For example, tables about songs of a producer can have the producer. This is to not give incorrect penalty to semantic descriptions including table subjects.
- add an additional semantic description for table `Gwendoline_Christie` which also is a correct way to model the table in Wikidata.
- fix semantic descriptions: `2013–14_Frauen-Bundesliga` should use Q51481377 instead of Q476028; `1985_PGA_Championship` should use Q6256 for country according to annotation guideline that the type should be true even when new row is added to the table; `17th_Saskatchewan_Legislature` should use Q6596424 as it is more specific than Q192611; `1967_NFL/AFL_Draft` should use Q17156793 instead of Q26895936 to consistent with descriptions of similar tables; `old_boys` add type to column 2 since P3876 is object property; `Local_government_areas_of_Scotland_(1973–1996)` population of district not region.

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
