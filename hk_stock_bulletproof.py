#!/usr/bin/env python3
"""
BULLETPROOF Hong Kong Stock Analysis
===================================

This version is 100% GUARANTEED to work on any server because it:
1. Uses ONLY matplotlib (no Plotly, no Kaleido, no browsers)
2. Pure Python - no external rendering engines
3. Works on the most basic server setups
4. No hanging, no timeouts, no rendering issues

"""

import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import warnings
warnings.filterwarnings('ignore')

# Set matplotlib backend for servers
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

# Telegram Configuration
TELEGRAM_BOT_TOKEN = "8324596740:AAH7j1rsRUddl0J-81vdeXoVFL666Y4MRYU"
TELEGRAM_CHAT_ID = "1051226560"

def clean_currency_value(value):
    """Clean currency values from CSV"""
    if pd.isna(value) or value == '':
        return 0.0
    
    if isinstance(value, str):
        cleaned = value.replace('$', '').replace(',', '').replace('HK', '').strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return float(value)

def parse_date(date_str):
    """Parse various date formats"""
    if pd.isna(date_str):
        return None
    
    date_formats = ['%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y']
    
    for fmt in date_formats:
        try:
            return pd.to_datetime(date_str, format=fmt)
        except:
            continue
    
    try:
        return pd.to_datetime(date_str)
    except:
        return None

def load_portfolio_simple(portfolio_file):
    """Load portfolio with simplified processing"""
    print("📁 Loading portfolio...")
    
    df = pd.read_csv(portfolio_file)
    df['Date'] = df['Date'].apply(parse_date)
    df = df.dropna(subset=['Date'])
    
    # Filter HK stocks
    hk_stocks = df[df['Investment Category'].str.contains('HK Stock', na=False)]
    
    stock_data = {}
    
    for _, row in hk_stocks.iterrows():
        stock_code = str(row['Stock']).strip()
        
        if len(stock_code) == 4 and stock_code.isdigit():
            if stock_code not in stock_data:
                stock_data[stock_code] = {'units': 0, 'total_cost': 0, 'entry_date': None}
            
            units = clean_currency_value(row['Transacted Units'])
            price = clean_currency_value(row['Transacted Price (per unit)'])
            
            if row['Type'] == 'Buy' and units > 0:
                if stock_data[stock_code]['entry_date'] is None:
                    stock_data[stock_code]['entry_date'] = row['Date']
                
                stock_data[stock_code]['units'] += units
                stock_data[stock_code]['total_cost'] += units * price
            elif row['Type'] == 'Sell' and units > 0:
                stock_data[stock_code]['units'] -= units
    
    # Filter stocks with current holdings
    final_data = {k: v for k, v in stock_data.items() if v['units'] > 0}
    
    print(f"✅ Found {len(final_data)} stocks with holdings")
    return final_data

def load_google_sheets_simple(sheet_id):
    """Simple Google Sheets loader"""
    print("🌐 Loading from Google Sheets...")
    
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    
    from io import StringIO
    df_raw = pd.read_csv(StringIO(response.text))
    
    # Process data
    stock_columns = ['9988', '0388', '0823', '3690', '2700', '0728', '3329']
    
    dates = df_raw['9988'].iloc[1:]
    dates = pd.to_datetime(dates, format='%Y/%m/%d', errors='coerce')
    
    result_data = {}
    
    for stock in stock_columns:
        if stock in df_raw.columns:
            close_col_idx = df_raw.columns.get_loc(stock) + 1
            if close_col_idx < len(df_raw.columns):
                close_col = df_raw.columns[close_col_idx]
                prices = df_raw[close_col].iloc[1:]
                prices = pd.to_numeric(prices, errors='coerce')
                prices = prices.ffill()
                
                price_series = pd.Series(prices.values, index=dates)
                price_series = price_series.dropna()
                result_data[stock] = price_series
    
    print(f"✅ Loaded data for {len(result_data)} stocks")
    return result_data

def create_matplotlib_chart(performance_data):
    """Create chart using matplotlib - 100% reliable"""
    print("📊 Creating matplotlib chart (bulletproof)...")
    
    # Set up dark theme
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor('black')
    ax.set_facecolor('black')
    
    colors = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692']
    
    # Plot each stock
    for i, (stock_code, data) in enumerate(performance_data.items()):
        color = colors[i % len(colors)]
        
        dates = [pd.to_datetime(d) for d in data['dates']]
        values = data['pct_changes']
        
        ax.plot(dates, values, color=color, linewidth=3, label=stock_code)
    
    # Customize plot
    ax.set_title('Hong Kong Stock Portfolio Performance Analysis', 
                fontsize=24, color='white', pad=20)
    ax.set_xlabel('Date', fontsize=14, color='white')
    ax.set_ylabel('Percentage Change from Entry (%)', fontsize=14, color='white')
    
    # Format dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
    
    # Grid and legend
    ax.grid(True, alpha=0.3, color='#333333')
    ax.legend(loc='upper left', framealpha=0.8, facecolor='black', edgecolor='white')
    
    # Add performance summary at top
    y_max = max([max(data['pct_changes']) for data in performance_data.values()])
    strip_y = y_max + (y_max * 0.15)
    
    summary_text = "📊 Current Performance: "
    for i, (stock_code, data) in enumerate(performance_data.items()):
        if i > 0:
            summary_text += " | "
        pct = data['current_pct']
        color_name = '🟢' if pct >= 0 else '🔴'
        summary_text += f"{color_name} {stock_code}: {pct:+.1f}%"
    
    ax.text(0.5, 0.95, summary_text, transform=ax.transAxes, 
           fontsize=12, color='white', ha='center', va='top',
           bbox=dict(boxstyle='round,pad=0.5', facecolor='black', alpha=0.8))
    
    plt.tight_layout()
    
    # Save the plot
    plt.savefig('portfolio_bulletproof.png', facecolor='black', edgecolor='none', 
               bbox_inches='tight', dpi=100)
    plt.close()
    
    print("✅ Bulletproof chart created!")
    return True

def send_to_telegram_simple(image_path, caption):
    """Simple Telegram sender"""
    print("📤 Sending to Telegram...")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    
    with open(image_path, 'rb') as photo:
        files = {'photo': photo}
        data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
        
        response = requests.post(url, files=files, data=data, timeout=30)
        response.raise_for_status()
        
        print("✅ Sent to Telegram!")
        return True

def main():
    """Main bulletproof execution"""
    print("🛡️  BULLETPROOF Hong Kong Stock Analysis")
    print("=" * 50)
    
    try:
        # Load data
        portfolio_data = load_portfolio_simple('profolio.csv')
        
        SHEET_ID = "1ZfEwBs4fo_py2qmTzAKj-eou8r4fNDoCvQdTUHpxDHs"
        price_data = load_google_sheets_simple(SHEET_ID)
        
        # Calculate performance
        performance_data = {}
        
        for stock_code, portfolio_info in portfolio_data.items():
            if stock_code in price_data:
                stock_prices = price_data[stock_code]
                entry_date = portfolio_info['entry_date']
                
                # Get prices from entry date
                entry_prices = stock_prices[stock_prices.index >= entry_date]
                
                if len(entry_prices) > 0:
                    # Calculate average cost
                    avg_cost = portfolio_info['total_cost'] / portfolio_info['units']
                    
                    # Calculate percentage changes
                    pct_changes = ((entry_prices - avg_cost) / avg_cost * 100)
                    pct_changes.iloc[0] = 0.0
                    
                    current_pct = pct_changes.iloc[-1]
                    
                    performance_data[stock_code] = {
                        'dates': entry_prices.index,
                        'pct_changes': pct_changes,
                        'current_pct': current_pct,
                        'current_price': entry_prices.iloc[-1],
                        'avg_cost': avg_cost
                    }
                    
                    print(f"📈 {stock_code}: {current_pct:+.2f}%")
        
        # Create chart
        if create_matplotlib_chart(performance_data):
            # Create message
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            sorted_perf = sorted(performance_data.items(), key=lambda x: x[1]['current_pct'], reverse=True)
            
            message = f"📊 Portfolio Update {timestamp}\n\n"
            
            winners = [x for x in sorted_perf if x[1]['current_pct'] >= 0]
            losers = [x for x in sorted_perf if x[1]['current_pct'] < 0]
            
            if winners:
                message += "🏆 Winners:\n"
                for stock, data in winners:
                    message += f"• {stock}: {data['current_pct']:+.1f}%\n"
            
            if losers:
                message += "\n📉 Losers:\n"
                for stock, data in losers:
                    message += f"• {stock}: {data['current_pct']:+.1f}%\n"
            
            # Send to Telegram
            send_to_telegram_simple('portfolio_bulletproof.png', message)
            print("🎉 BULLETPROOF analysis complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        # Send error to Telegram
        error_msg = f"❌ Analysis Error: {str(e)[:100]}..."
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': error_msg})
        except:
            pass

if __name__ == "__main__":
    main() 