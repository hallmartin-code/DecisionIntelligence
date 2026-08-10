"""Generate `samples/sample_deck.pdf`, a synthetic pitch deck for smoke tests.

Run with:  python samples/make_sample_deck.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

SLIDES: list[tuple[str, list[str]]] = [
    (
        "Northwind Robotics",
        [
            "Warehouse picking automation for mid-size distribution centers",
            "Seed round - $4.0M - August 2026",
        ],
    ),
    (
        "The Problem",
        [
            "US warehouses ran 490,000 unfilled picking roles in 2025 (BLS).",
            "Turnover in manual picking averages 46% annually.",
            "Existing robotic arms cost $310K installed - out of reach below",
            "50,000 sq ft of floorspace.",
            "Operators pay $71K fully loaded per picker per year.",
        ],
    ),
    (
        "Our Solution",
        [
            "The NW-1 arm: a retrofit picking cell that mounts to existing",
            "conveyor lines in under four hours.",
            "Force-feedback gripper handles mixed-SKU totes without retooling.",
            "Installed cost $148K, roughly half the incumbent price point.",
            "Runs on standard 240V; no facility rewiring required.",
        ],
    ),
    (
        "How It Works",
        [
            "Vision stack trained on 2.1M labeled tote images from pilot sites.",
            "Pick success rate 98.4% across 14 SKU categories (internal testing).",
            "Cycle time 4.2 seconds vs 6.1 seconds for a human picker.",
            "Edge inference on-device; no cloud dependency during operation.",
        ],
    ),
    (
        "Market",
        [
            "TAM: $12B - global warehouse automation hardware, 2030.",
            "SAM: 21,400 US distribution centers between 20K and 50K sq ft.",
            "At 3 arms per site and $148K ASP, that is a $9.5B serviceable market.",
            "Beachhead: third-party logistics operators in the US Midwest.",
        ],
    ),
    (
        "Traction",
        [
            "Two paid pilots converted to three-year contracts in Q2 2026.",
            "Midwest Fulfillment Co - 6 arms deployed, $890K contract value.",
            "Cardinal 3PL - 4 arms deployed, $592K contract value.",
            "$1.48M of contracted revenue; $310K recognized to date.",
            "Letter of intent from a third operator for 12 arms, pending pilot.",
        ],
    ),
    (
        "Business Model",
        [
            "Hardware sale at $148K per arm plus $18K/year service contract.",
            "Current gross margin 31%; modeled at 52% at 500 units/year.",
            "Payback for the customer: 14 months at current labor rates.",
            "Net revenue retention 100% (both pilot accounts expanded).",
        ],
    ),
    (
        "Team",
        [
            "Dr. Elena Vasquez, CEO - previously Principal Robotics Engineer at",
            "a public warehouse automation firm; shipped two arm platforms.",
            "Marcus Chen, CTO - 11 years in computer vision; PhD, CMU.",
            "Priya Raman, VP Operations - scaled contract manufacturing at a",
            "consumer hardware company from 2K to 80K units/year.",
            "Open role: VP Sales. No commercial hire to date.",
        ],
    ),
    (
        "Competition",
        [
            "Incumbent A: $310K installed, targets 100K+ sq ft facilities.",
            "Incumbent B: European, well funded, shipping a comparable arm",
            "into EU logistics since Q4 2025; no US presence announced.",
            "Two provisional patents filed on the gripper mechanism.",
            "No composition or method patents granted to date.",
        ],
    ),
    (
        "The Ask",
        [
            "Raising $4.0M on a $18M post-money SAFE, 20% discount.",
            "$1.6M committed; seeking a lead for the remaining $2.4M.",
            "Use of proceeds: $1.7M engineering, $1.1M contract manufacturing",
            "NRE, $0.8M go-to-market, $0.4M working capital.",
            "18 months of runway to a Series A at 40 arms deployed.",
            "Contract manufacturer not yet selected; actuator supply agreement",
            "unsigned as of this deck.",
        ],
    ),
]


def build(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    page = landscape(letter)
    pdf = canvas.Canvas(str(destination), pagesize=page)
    width, height = page

    for title, lines in SLIDES:
        pdf.setFont("Helvetica-Bold", 30)
        pdf.drawString(64, height - 96, title)
        pdf.setFont("Helvetica", 15)
        y = height - 150
        for line in lines:
            pdf.drawString(64, y, line)
            y -= 26
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(width - 64, 36, "Confidential")
        pdf.showPage()

    pdf.save()
    return destination


if __name__ == "__main__":
    path = build(Path(__file__).resolve().parent / "sample_deck.pdf")
    print(f"Wrote {path}")
