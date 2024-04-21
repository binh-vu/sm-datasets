# Changelog

## [2.0.3] - 2024-04-21

### Added

- Add `t2dv2` dataset & script to normalize it & add to the `Datasets` class.

### Changed

- Move datasets to `sm_datasets/datasets` directory

### Fixed

- Invalid dataset directory
- Use the `kgns.id_to_uri` function of the provided `kgns` instead of fixed wikidata namespace.
- Reset `readable_label` when fixing redirected classes or properties.
- Remove duplicated entities after fixing redirections.
- Use `table.get_column_by_index` instead of directly access `table.columns`
