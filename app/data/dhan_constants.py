"""Exchange segment / instrument type constants used by the DhanHQ v2 API.

Column names below were verified against the live instrument master CSV on
2026-08-29 (the published docs use an outdated SEM_-prefixed schema that does
not match the actual file).
"""

EXCHANGE_SEGMENT_NSE_EQ = "NSE_EQ"
EXCHANGE_SEGMENT_NSE_FNO = "NSE_FNO"
EXCHANGE_SEGMENT_IDX_I = "IDX_I"

INSTRUMENT_EQUITY = "EQUITY"
INSTRUMENT_FUTSTK = "FUTSTK"
INSTRUMENT_OPTSTK = "OPTSTK"
INSTRUMENT_INDEX = "INDEX"

INSTRUMENT_MASTER_DETAILED_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"

# Columns in the detailed instrument master CSV (verified live schema).
COL_EXCH_ID = "EXCH_ID"
COL_SEGMENT = "SEGMENT"
COL_SECURITY_ID = "SECURITY_ID"
COL_INSTRUMENT = "INSTRUMENT"
COL_UNDERLYING_SECURITY_ID = "UNDERLYING_SECURITY_ID"
COL_UNDERLYING_SYMBOL = "UNDERLYING_SYMBOL"
COL_SYMBOL_NAME = "SYMBOL_NAME"
COL_DISPLAY_NAME = "DISPLAY_NAME"
COL_SERIES = "SERIES"
COL_LOT_SIZE = "LOT_SIZE"
COL_EXPIRY_DATE = "SM_EXPIRY_DATE"
COL_STRIKE_PRICE = "STRIKE_PRICE"
COL_OPTION_TYPE = "OPTION_TYPE"

# Segment codes.
SEGMENT_DERIVATIVES = "D"
SEGMENT_EQUITY = "E"

# UNDERLYING_SYMBOL values that are exchange test scrips, not real stocks.
TEST_SYMBOL_MARKER = "NSETEST"
