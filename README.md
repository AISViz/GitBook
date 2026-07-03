# AISViz GitBook

Source for the AISdb user documentation and tutorials, published through GitBook at
[aisviz.gitbook.io/documentation](https://aisviz.gitbook.io/documentation/). This repository holds
the Markdown pages, navigation, and image assets behind the guides, and it is the companion
documentation project to the [AISdb](https://github.com/MAPS-Lab/AISdb) library. Content tracks
release 1.8.0-alpha.

AISdb is an open-source system for storing, processing, analysing, and visualising Automatic
Identification System (AIS) vessel-tracking data. It is built on SQLite and PostgreSQL with a Rust
core and a Python interface. These pages walk a reader from a first install through querying,
cleaning, enriching, and modelling AIS trajectories.

## How the GitBook sync works

GitBook and this repository sync in both directions. Edits made in the GitBook editor arrive here
as sync commits on `main`, and commits pushed here are picked up by GitBook and published. The
integration is configured in [`.gitbook.yaml`](.gitbook.yaml). Its `structure.readme` key points
GitBook at `introduction.md` for the landing page, which leaves this `README.md` free to describe
the repository on GitHub, and its `structure.summary` key points at [`SUMMARY.md`](SUMMARY.md),
which defines the table of contents. Figures uploaded through the editor live under
`.gitbook/assets/`. A page only appears in the published book after it is listed in `SUMMARY.md`.

## Contributing a docs change

Edit the relevant Markdown file, keep GitBook front matter and hint or figure syntax intact, add
any new page to `SUMMARY.md`, and open a pull request against `main`. Every push and pull request
runs the docs QA workflow in `.github/workflows/docs-qa.yml`, which executes
`.github/scripts/docs_qa.py` and fails on broken internal links, missing assets, unbalanced code
fences, editorial drift, and references to retired hosts or repositories. Please confirm that every
AISdb call in an example matches the release noted at the top of this file. Questions and larger
proposals can go through the [MAPS Lab organisation](https://github.com/MAPS-Lab).

## Documentation

- [Documentation](https://aisviz.gitbook.io/documentation/)
- [Tutorials](https://aisviz.gitbook.io/tutorials/)
- [API reference](https://aisviz.cs.dal.ca/AISdb/)
- [Website](https://aisviz.cs.dal.ca/)

## Related projects

- [AISdb](https://github.com/MAPS-Lab/AISdb) is the Python package for smart AIS data storage and
  integration.
- [AISdb-lite](https://github.com/MAPS-Lab/AISdb-lite) is a lightweight version of AISdb with
  spatio-temporal capabilities on PostGIS and TigerData.
- [NOAA-Integrator](https://github.com/MAPS-Lab/AISdb-NOAA-Integrator) acquires and processes Marine
  Cadastre AIS data into an AISdb-aligned database.
- [Tutorials](https://github.com/MAPS-Lab/AISdb-Tutorials) holds hands-on Jupyter notebooks that walk
  through AISdb, from database loading to bathymetry.

## License

This documentation is released under the [AGPL-3.0 license](LICENSE). It is maintained by the
MAPS Lab team in the MAPS Lab at Dalhousie University, in collaboration with the Maritime Risk and
Safety (MARS) group, building on earlier work from the MERIDIAN initiative. Reach the maintainers
at [mapslab@dal.ca](mailto:mapslab@dal.ca).
