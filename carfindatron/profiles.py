"""What to search for: one profile per vehicle, each with its own sources, trim rules and report page."""

from dataclasses import dataclass, field

CROWN_PLATINUM_VIN = "JTDAFAAF"
ES_TRIM_BY_VIN = {"E": "Luxury", "F": "Ultra Luxury", "B": "F Sport Handling", "J": "F Sport Handling",
                  "C": "Base", "D": "Base / F Sport Design"}


@dataclass(frozen=True)
class Profile:
    key: str
    title: str
    make: str
    carfax_model: str
    brand: str
    series: str
    dealer_brand: int
    years: tuple
    focus: tuple
    sources: tuple
    miles: tuple = None
    trim_rules: dict = field(default_factory=dict)

    def matches(self, vin):
        vin = vin.upper()
        if self.key == "crown":
            return vin.startswith("JTDA")
        if self.key == "es300h":
            return vin.startswith("58A") and vin[4:7] == "A1C"
        return True

    def trim(self, vin, raw):
        vin = vin.upper()
        if self.key == "crown":
            if vin.startswith(CROWN_PLATINUM_VIN):
                return "Platinum"
            s = (raw or "").lower()
            return next((t for t in ("Nightshade", "Limited", "XLE") if t.lower() in s), None)
        if self.key == "es300h":
            return ES_TRIM_BY_VIN.get(vin[3]) if len(vin) > 3 else None
        return raw


CROWN = Profile(
    key="crown", title="Toyota Crown Platinum", make="Toyota", carfax_model="Crown", brand="TOYOTA",
    series="toyotacrown", dealer_brand=1, years=(2025, 2026), focus=("Platinum",),
    sources=("carfax", "toyota", "carfax_new", "toyota_new"))

ES300H = Profile(
    key="es300h", title="Lexus ES 300h Luxury / Ultra Luxury", make="Lexus", carfax_model="ES", brand="LEXUS",
    series="ESh", dealer_brand=2, years=(2025, 2025), focus=("Luxury", "Ultra Luxury"),
    sources=("carfax", "toyota"), miles=(10000, 25000))

PROFILES = {p.key: p for p in (CROWN, ES300H)}
