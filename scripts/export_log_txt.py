"""CLI：批量将 log/raw/*.json 导出为 log/content/*.txt（与 persist 使用同一套逻辑）。"""

from context.content_export import export_raw_logs_to_txt


def main() -> None:
    export_raw_logs_to_txt()


if __name__ == "__main__":
    main()
