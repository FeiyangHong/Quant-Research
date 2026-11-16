"""Optional offline figures from frozen exported results; never starts accounts."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/m8_rotation'


def main():
    paths = json.loads((REPORT / 'ACCOUNT_PATHS.json').read_bytes())
    figure, axes = plt.subplots(1, 2, figsize=(13, 4.4), sharey=False)
    for ax, period, title in zip(axes, ('development', 'validation'),
                                ('Development: 2020-2021', 'Observed validation: 2022-2024')):
        for variant, color in zip(('E0', 'R0', 'E1', 'R1'), ('#505b6b', '#1565c0', '#c46c13', '#1a7f50')):
            row = next(r for r in paths if r['period'] == period and r['path'] == 'base' and r['variant'] == variant)
            if row['status'] != 'COMPLETED':
                raise ValueError('Do not plot an unrun or failed account as zero return')
            nav = pd.read_json(ROOT / row['artifact_directory'] / 'nav.json')
            ax.plot(pd.to_datetime(nav.date), nav.nav, label=variant, color=color, lw=1.35)
        ax.set_xlim(pd.to_datetime(nav.date).min(), pd.to_datetime(nav.date).max())
        ax.axhline(100000, color='#999999', ls=':', lw=.8)
        ax.set_title(title)
        ax.set_ylabel('Net account value (CNY)')
        ax.grid(alpha=.18)
        ax.legend(frameon=False, ncol=4)
        ax.tick_params(axis='x', rotation=25)
    figure.suptitle('M8 fixed historical cohort | 100,000 CNY | costs included | daily-screen simulation', fontsize=11)
    figure.tight_layout()
    figure.savefig(REPORT / 'base_nav.png', dpi=160)
    figure.savefig(REPORT / 'base_nav.svg')
    plt.close(figure)


if __name__ == '__main__':
    main()
