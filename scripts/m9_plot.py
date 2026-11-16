"""Optional export of frozen M9 NAVs; never changes or runs an account."""
import json
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/m9_risk"


def main():
    paths = json.loads((REPORT / "ACCOUNT_PATHS.json").read_bytes())
    fig, axes = plt.subplots(1,2,figsize=(13,4.6))
    for axis,period in zip(axes,("development","validation")):
        for variant,color in (("VE","#1765b7"),("CE","#4f5966"),("VR","#16835e")):
            row=next(x for x in paths if x["period"]==period and x["path"]=="base" and x["variant"]==variant)
            nav=pd.DataFrame(json.loads((REPORT/"accounts"/row["trial_id"]/"nav.json").read_bytes()))
            dates=pd.to_datetime(nav.date)
            axis.plot(dates,nav.nav,label=variant,color=color,linewidth=1.4)
        axis.set_xlim(dates.min(),dates.max())
        axis.axhline(100000,color="gray",linestyle=":",linewidth=.7)
        axis.set_title("Development 2020-2021" if period=="development" else "Observed validation 2022-2024")
        axis.grid(alpha=.15);axis.legend();axis.tick_params(axis="x",rotation=25)
    axes[0].set_ylabel("Simulated net account value (CNY)")
    fig.suptitle("M9 fixed risk policies | 100,000 CNY per period | costs included")
    fig.tight_layout();fig.savefig(REPORT/"base_nav.png",dpi=160);plt.close(fig)


if __name__ == "__main__":
    main()
