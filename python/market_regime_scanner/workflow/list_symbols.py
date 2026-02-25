"""List all symbols available in the MT5 terminal."""
import MetaTrader5 as mt5


def main():
    if not mt5.initialize():
        raise ConnectionError(f"Could not initialize MT5: {mt5.last_error()}")

    symbols = mt5.symbols_get()
    print(f"Total symbols: {len(symbols)}")
    for s in symbols:
        print(f"{s.name} (visible={s.visible})")

    mt5.shutdown()


if __name__ == "__main__":
    main()
