# carfindatron

carfindatron searches public dealer listings for specific cars, ranks them by what they would cost you to own and bring home, and writes a sortable HTML report for each vehicle. It keeps every scan in a local SQLite database, so repeated runs show price history, price drops and cars that have sold.

It currently searches for two vehicles:

| Profile | Vehicle | Listings |
|---|---|---|
| `crown` | Toyota Crown Platinum, 2025-2026 | certified pre-owned and new |
| `es300h` | Lexus ES 300h Luxury and Ultra Luxury, 2025 | certified pre-owned (L/Certified) |

Sources are Carfax, Toyota Certified and Lexus Certified inventory, and toyota.com new-car inventory.

## Requirements

- macOS. Scheduling and notifications use launchd and macOS notifications.
- [uv](https://docs.astral.sh/uv/)
- Google Chrome, for the toyota.com new-car source only. It runs in a window placed off screen for about ten seconds per scan.

## Install

```
git clone https://github.com/unxmaal/carfindatron.git
cd carfindatron
uv sync
```

## Set your search location

Distances, delivery costs and the "nearest" figures are measured from a ZIP code you supply. Save it once:

```
uv run carfindatron --zip 10001 --save-zip
```

This writes `~/.config/carfindatron/config.json`. The `CARFINDATRON_ZIP` environment variable overrides it. Without a ZIP, the scanner stops with an error.

## Run a scan

```
uv run carfindatron --open
```

A full scan takes about 30 to 40 seconds. It prints a summary per vehicle in the terminal and writes the reports to `~/.local/share/carfindatron/`:

- `report.html`: the first vehicle (the Crown)
- `report-crown.html`, `report-es300h.html`: one page per vehicle, linked to each other by tabs at the top

Common variations:

```
uv run carfindatron --profiles es300h            # one vehicle
uv run carfindatron --sources carfax,toyota      # skip the browser-based toyota.com source
uv run carfindatron --report-only --open         # rebuild the pages from the last scan, no fetching
```

## Reading the report

The top of each page shows headline numbers (median price, lowest price, nearest car, the car furthest under market value), a price trend across scans, and a chart comparing each state's prices with the national market.

The table has one row per car. Click a column header to sort; click it again to reverse. The line above the table says what it is sorted by, and "cheapest effective cost first" restores the default.

| Column | Meaning |
|---|---|
| Effective cost | Price, plus a charge for odometer miles at the market's per-mile rate, plus the dealer's fees, plus the cost of getting the car home. Lower is better. A star marks a car no other car of the same trim beats on price, miles and distance at once. |
| Price | The lowest asking price found. Smaller lines show MSRP and the price on other sites when they differ. |
| Offer | A suggested opening offer and a fair-price estimate, with an out-the-door target. Hover for how it was worked out. |
| Miles, Distance | Odometer miles, and miles from your ZIP with the cost of getting the car home. |
| Fees | Dealer fees you would likely pay. A red "to fight" tag means an optional package, a questionable charge or a high doc fee; hover for the itemized list. A `*` means the fee was not on the listing and is estimated. |
| Days listed | Days since the dealer acquired or first listed the car. A `*` means no dealer date was available and the count starts from the first scan that saw the car. |
| Car | Year, trim, new or CPO, and prior use (personal, lease, fleet, rental, commercial). Rental and commercial cars are tagged in red, lease returns in green. |
| vs model | Asking price minus what the market model expects for that trim, year and mileage. Negative is cheaper than the market. A "deal" tag marks cars well under. |
| Leverage | Signs that the dealer has room to move on price. Hover for the reasons. |
| History | Price over past scans, with the change since the last scan. |
| Color | Paint and interior. A black band on the swatch marks a two-tone car with a black roof. |
| Dealer | Opens the listing. The smaller "dealer inventory" link opens the dealer's own inventory page as a fallback. When only the dealer page is available, the VIN is shown so you can find the car there. |

### Filters

Above the table: condition (new or CPO), trim, mileage range, maximum distance, and whether to hide cars with an accident or damage report. **Exclude…** opens checkboxes for prior use, exterior color, roof and interior. Exclusions are remembered in your browser.

The ES 300h page opens filtered to Luxury and Ultra Luxury between 10,000 and 25,000 miles.

## How far away is too far

Within 200 miles of your ZIP, getting the car home costs nothing (you drive over). Beyond that, the report prices a remote purchase: open-carrier shipping at $350 plus $0.60 per mile (minimum $500) and a $200 independent pre-purchase inspection. Change these to match a quote you receive:

```
uv run carfindatron --free-radius 150 --ship-base 400 --ship-per-mile 0.70 --inspection 250
```

`--per-mile` sets the charge per odometer mile. By default it is the rate the market applies in the current scan.

## Daily runs

```
./scripts/schedule.sh install          # daily at 07:15
./scripts/schedule.sh install 06:30    # another time
./scripts/schedule.sh status           # schedule, last result, number of runs
./scripts/schedule.sh run              # run now
./scripts/schedule.sh remove
```

Scheduled runs post a macOS notification when a car in the focus trims appears or drops in price, or when a source fails. A Mac asleep at the scheduled time runs the scan when it wakes. Output goes to `~/.local/share/carfindatron/daily.log`.

## Options

| Option | Default | Effect |
|---|---|---|
| `--zip`, `--save-zip` | from config | Search origin; `--save-zip` stores it |
| `--profiles` | all | Vehicles to scan: `crown`, `es300h` |
| `--sources` | all | `carfax`, `toyota`, `carfax_new`, `toyota_new` |
| `--free-radius` | 200 | Miles you would drive to collect a car |
| `--ship-base`, `--ship-per-mile`, `--ship-min` | 350, 0.60, 500 | Shipping estimate beyond the radius |
| `--inspection` | 200 | Pre-purchase inspection for a remote purchase |
| `--per-mile` | market rate | Charge per odometer mile |
| `--db`, `--html` | `~/.local/share/carfindatron/` | Database and landing page locations |
| `--report-only` | off | Rebuild pages from the last scan |
| `--open` | off | Open the report when done |
| `--notify` | off | Notify on new cars and price drops |

## Limits

The offer, leverage and market-model figures are estimates from public listings. No sale prices go into them. Fees missing from a listing are estimated, and delivery costs use typical market rates. Ask dealers for an itemized out-the-door price in writing before relying on any figure here.
