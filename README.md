# ChargeAhead charging prices

Per-operator EV charging prices, per kWh with VAT, as each operator
publishes them on its own website or app, with the day they were last
checked. The [ChargeAhead](https://github.com/sami79031) app shows them on
charging stops.

| File | Country | Currency |
|---|---|---|
| [`tr.json`](tr.json) | Türkiye | TRY |

Prices are list prices: operators may charge less at some places or times,
and app or membership prices can differ. They are checked weekly and every
change is reviewed before it is published. They are provided as-is,
without warranty: the price that applies is the one the operator shows at
the start of charging.

## Open-data sources

Prices for the Netherlands and Germany are pay-at-the-charger (ad hoc)
prices from open data, imported daily by `feeds.py` into per-area files on
the [`feeds`](../../tree/feeds) branch.

| Country | Source | Licence |
|---|---|---|
| Netherlands | [NDW open data](https://opendata.ndw.nu/), charging point locations and tariffs (OCPI) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| Germany | [MobiData BW](https://www.mobidata-bw.de/), "Gebündelte Daten E-Ladesäulen" ([OCPDB](https://api.mobidata-bw.de/ocpdb/)) | [Datenlizenz Deutschland – Namensnennung – 2.0](https://www.govdata.de/dl-de/by-2-0) |
| Germany, within MobiData BW | Eco-Movement, EnBW AG | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| Germany, within MobiData BW | chargecloud, Wirelane, Smatrics, Inergia | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

Changes made to the data: only prices for paying at the charger are kept;
VAT is added where the source gives it separately, and prices whose VAT is
not given are left out; blocking fees and parking are left out; sites are
matched to ChargeAhead's stations by position and operator. Each price in
the app names its source.

`python3 prices.py validate` checks the files; `python3 prices.py summary`
shows what a branch changes.

The hand-kept tables (`tr.json`) and the code are released under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/): use them
freely. The open data on the `feeds` branch keeps its sources' licences
(above).
