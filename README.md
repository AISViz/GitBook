# AISdb Documentation

AISdb Documentation is the Markdown source for the AISdb user guides and tutorials, published through GitBook at [aisviz.gitbook.io/documentation](https://aisviz.gitbook.io/documentation/). This repository holds the documentation pages, the navigation table of contents, and the image assets behind the guides, and it is the companion documentation project to the [AISdb](https://github.com/MAPS-Lab/AISdb) library. Content tracks release 1.8.0-alpha. The documentation is developed and maintained by the [MAPS Lab](https://mapslab.tech/) at Dalhousie University, continuing work that began under the [MERIDIAN](https://meridian.cs.dal.ca) initiative.

AISdb is an open-source system for storing, processing, analysing, and visualising Automatic Identification System (AIS) vessel-tracking data, built on SQLite and PostgreSQL with a Rust core and a Python interface. These pages walk a reader from a first install through querying, cleaning, enriching, and modelling AIS trajectories.

## Structure

The book is organised by the table of contents in [`SUMMARY.md`](SUMMARY.md), which groups the pages into the following areas.

- [`introduction.md`](introduction.md) is the landing page, with an overview of AISdb, the research programme, and the team.
- `default-start/` covers the first steps, including the quick start, the SQL database, and AIS hardware.
- `tutorials/` holds hands-on guides from database loading and querying through cleaning, visualisation, interpolation, vessel metadata, and bathymetric and weather enrichment.
- `machine-learning/` covers modelling workflows, including clustering, Kalman filters, sequence models, autoencoders, trajectory embeddings, physics-informed networks, temporal graph networks, and a retrieval-augmented chatbot.
- `.gitbook/assets/` stores the figures uploaded through the GitBook editor.

## How it is published

GitBook and this repository sync in both directions. Edits made in the GitBook editor arrive here as sync commits on `main`, and commits pushed here are picked up by GitBook and published. The integration is configured in [`.gitbook.yaml`](.gitbook.yaml). Its `structure.readme` key points GitBook at `introduction.md` for the published landing page, which leaves this `README.md` free to describe the repository on GitHub, and its `structure.summary` key points at `SUMMARY.md`, which defines the table of contents. A page only appears in the published book after it is listed in `SUMMARY.md`.

## How to contribute

Edit the relevant Markdown file, keep the GitBook front matter and the hint or figure syntax intact, add any new page to `SUMMARY.md`, and open a pull request against `main`. Every push and pull request runs the docs QA workflow in `.github/workflows/docs-qa.yml`, which executes `.github/scripts/docs_qa.py` and fails on broken internal links, missing assets, unbalanced code fences, editorial drift, and references to retired hosts or repositories. Please confirm that every AISdb call in an example matches the release noted at the top of this file. Questions and larger proposals can go through the [MAPS Lab organisation](https://github.com/MAPS-Lab).

## Documentation

- [Documentation](https://aisviz.gitbook.io/documentation/)
- [Tutorials](https://aisviz.gitbook.io/tutorials/)
- [API reference](https://aisviz.cs.dal.ca/AISdb/)
- [Website](https://aisviz.cs.dal.ca/)

## Related projects

- [AISdb](https://github.com/MAPS-Lab/AISdb) is the Python package for smart AIS data storage and integration.
- [AISdb-lite](https://github.com/MAPS-Lab/AISdb-lite) is a lightweight version of AISdb with spatio-temporal capabilities on PostGIS and TigerData.
- [NOAA-Integrator](https://github.com/MAPS-Lab/NOAA-Integrator) acquires and processes Marine Cadastre AIS data into an AISdb-aligned database.
- [AISdb-Tutorials](https://github.com/MAPS-Lab/AISdb-Tutorials) holds hands-on Jupyter notebooks that walk through AISdb, from database loading to bathymetry.

## License

This documentation is distributed under the terms of the GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE) for details. It is maintained by the [MAPS Lab](https://mapslab.tech/) at Dalhousie University, in collaboration with the [Maritime Risk and Safety (MARS)](https://www.maritimeriskandsafety.ca/) group, building on earlier work from the MERIDIAN initiative. Reach the maintainers at [mapslab@dal.ca](mailto:mapslab@dal.ca).
