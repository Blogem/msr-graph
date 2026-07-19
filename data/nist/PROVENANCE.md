# Provenance: NIST Properties of Molten Salts Database (SRD 27)

- **Dataset title**: NIST Properties of Molten Salts Database (formerly SRD 27)
- **DOI**: [10.18434/mds2-2298](https://doi.org/10.18434/mds2-2298)
- **Landing page**: https://data.nist.gov/od/id/mds2-2298
- **Retrieval date**: 2026-07-19

## Vendored files

| File | Source URL |
|------|------------|
| `density-csv.txt` | https://data.nist.gov/od/ds/mds2-2298/density-csv.txt |
| `conductivity-csv.txt` | https://data.nist.gov/od/ds/mds2-2298/conductivity-csv.txt |
| `s-tension-csv.txt` | https://data.nist.gov/od/ds/mds2-2298/s-tension-csv.txt |
| `viscosity-csv.txt` | https://data.nist.gov/od/ds/mds2-2298/viscosity-csv.txt |

Each file's SHA-256 checksum was verified against the upstream `<name>.sha256` sibling at retrieval time.

## Licensing

This is a work of the U.S. Government (NIST) and is therefore in the public domain in the United States, effectively public domain; there is no EULA. When reused, attribute to the DOI above (`10.18434/mds2-2298`).

## Note for maintainers

This vendored copy is the frozen input the loader reads — the loader never fetches from the network. Each file begins with a title line and a blank line before the 13-column CSV header (e.g. `Salt,Composition range,Data type,T min (K),T max (K),Uncertainty,Data 1,Data 2,Data 3,Data 4,Data 5,Comment,Formatting comment` on line 3); this structure is intentional and must not be stripped or reformatted.
