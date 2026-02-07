from .recipe_categorizer import main as categorizer_main


def main():
    categorizer_main(forced_provider="chatgpt")


if __name__ == "__main__":
    main()
