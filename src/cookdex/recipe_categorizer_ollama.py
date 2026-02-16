from .recipe_categorizer import main as categorizer_main


def main():
    categorizer_main(forced_provider="ollama")


if __name__ == "__main__":
    main()
