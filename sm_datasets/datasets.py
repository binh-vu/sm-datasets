from pathlib import Path
from sm.dataset import Dataset

ROOT_DIR = Path(__file__).parent.parent.absolute()


class Datasets:
    @staticmethod
    def wt250():
        return Dataset(ROOT_DIR / "250wt").load()

    @staticmethod
    def semtab2020r4():
        return Dataset(ROOT_DIR / "semtab2020_round4").load()

    @staticmethod
    def biotable():
        return Dataset(ROOT_DIR / "biotables").load()


if __name__ == "__main__":
    # exs = Datasets.wt250()
    exs = Datasets.biotable()
    print(len(exs))
