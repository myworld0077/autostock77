import FinanceDataReader as fdr
import pandas as pd
from core.universe import get_kis_kospi200_top150

# Get the top 150 KOSPI 200 stocks
try:
    top150 = get_kis_kospi200_top150()
    print(f"Top 150 length: {len(top150)}")
    
    # Get stock listing
    df = fdr.StockListing('KOSPI')
    
    # Filter by top150
    df['Code'] = df['Code'].astype(str).str.zfill(6)
    df_filtered = df[df['Code'].isin(top150)].copy()
    print(f"Filtered df length: {len(df_filtered)}")
    
    df_filtered['ChagesRatio'] = pd.to_numeric(df_filtered['ChagesRatio'], errors='coerce').fillna(0.0)
    df_filtered['Amount'] = pd.to_numeric(df_filtered['Amount'], errors='coerce').fillna(0.0)
    
    # Rank by ChagesRatio descending (highest daily gainers)
    df_gainers = df_filtered.sort_values(by='ChagesRatio', ascending=False)
    print("\n--- Top 10 by ChagesRatio ---")
    for i, row in df_gainers.head(10).iterrows():
        print(f"{row['Code']} ({row['Name']}): Change {row['ChagesRatio']}% | Amount {row['Amount']/1e8:.1f}억")
        
    # Rank by Amount descending (highest transaction value)
    df_amount = df_filtered.sort_values(by='Amount', ascending=False)
    print("\n--- Top 10 by Transaction Amount ---")
    for i, row in df_amount.head(10).iterrows():
        print(f"{row['Code']} ({row['Name']}): Change {row['ChagesRatio']}% | Amount {row['Amount']/1e8:.1f}억")

except Exception as e:
    import traceback
    traceback.print_exc()
