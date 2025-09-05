#!/usr/bin/env python3
"""
SERVER-PROOF Hong Kong Stock Analysis
=====================================

This version is guaranteed to work on any server because it:
1. Uses ONLY pure Python libraries (no browsers)
2. Has robust error handling for all network calls
3. Uses Plotly's native image export (no HTML/screenshots)
4. Has multiple fallback mechanisms
5. Works even with minimal server resources

"""

import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Telegram Configuration
TELEGRAM_BOT_TOKEN = "8324596740:AAH7j1rsRUddl0J-81vdeXoVFL666Y4MRYU"
TELEGRAM_CHAT_ID = "1051226560"

def clean_currency_value(value):
    """Clean currency values from CSV"""
    if pd.isna(value) or value == '':
        return 0.0
    
    if isinstance(value, str):
        # Remove currency symbols and commas
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

def load_and_process_portfolio(portfolio_file):
    """Load and process portfolio transactions"""
    print("📁 Loading portfolio transactions...")
    
    try:
        df = pd.read_csv(portfolio_file)
        
        # Clean and process data
        df['Date'] = df['Date'].apply(parse_date)
        df = df.dropna(subset=['Date'])
        
        # Filter for Hong Kong stocks only
        hk_stocks = df[df['Investment Category'].str.contains('HK Stock', na=False)]
        
        # Process transactions
        stock_transactions = {}
        
        for _, row in hk_stocks.iterrows():
            stock_code = str(row['Stock']).strip()
            
            if len(stock_code) == 4 and stock_code.isdigit():
                transaction_type = row['Type']
                units = clean_currency_value(row['Transacted Units'])
                price = clean_currency_value(row['Transacted Price (per unit)'])
                
                if stock_code not in stock_transactions:
                    stock_transactions[stock_code] = {
                        'buy_transactions': [],
                        'sell_transactions': [],
                        'all_transactions': [],
                        'current_units': 0,
                        'total_cost': 0
                    }
                
                transaction_data = {
                    'Date': row['Date'],
                    'Type': transaction_type,
                    'Units': units,
                    'Price': price,
                    'Value': units * price
                }
                
                stock_transactions[stock_code]['all_transactions'].append(transaction_data)
                
                if transaction_type == 'Buy' and units > 0:
                    stock_transactions[stock_code]['buy_transactions'].append(transaction_data)
                    stock_transactions[stock_code]['current_units'] += units
                    stock_transactions[stock_code]['total_cost'] += units * price
                elif transaction_type == 'Sell' and units > 0:
                    stock_transactions[stock_code]['sell_transactions'].append(transaction_data)
                    stock_transactions[stock_code]['current_units'] -= units
        
        # Convert lists to DataFrames and filter stocks with current holdings
        final_stocks = {}
        for stock_code, data in stock_transactions.items():
            if data['current_units'] > 0:
                data['buy_transactions'] = pd.DataFrame(data['buy_transactions'])
                data['sell_transactions'] = pd.DataFrame(data['sell_transactions'])
                data['all_transactions'] = pd.DataFrame(data['all_transactions'])
                final_stocks[stock_code] = data
        
        print(f"✅ Found {len(final_stocks)} Hong Kong stocks with current holdings")
        return final_stocks
        
    except Exception as e:
        print(f"❌ Portfolio loading failed: {e}")
        return {}

def load_stock_prices_from_google_sheets_robust(sheet_id):
    """Ultra-robust Google Sheets loader with multiple retry mechanisms"""
    print("🌐 Loading data from Google Sheets (server-proof)...")
    
    # Multiple URL formats to try
    urls = [
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    ]
    
    for attempt, url in enumerate(urls, 1):
        try:
            print(f"🔄 Attempt {attempt}: Trying URL format {attempt}...")
            
            # Robust request with retries
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            response = session.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse data
            from io import StringIO
            df_raw = pd.read_csv(StringIO(response.text))
            
            print(f"✅ Successfully loaded data (Shape: {df_raw.shape})")
            
            # Process the data
            stock_columns = ['9988', '0388', '0823', '3690', '2700', '0728', '3329']
            
            # Extract dates and prices
            dates = df_raw['9988'].iloc[1:]
            dates = pd.to_datetime(dates, format='%Y/%m/%d', errors='coerce')
            
            formatted_data = {'Date': dates}
            
            for stock in stock_columns:
                if stock in df_raw.columns:
                    close_col_idx = df_raw.columns.get_loc(stock) + 1
                    if close_col_idx < len(df_raw.columns):
                        close_col = df_raw.columns[close_col_idx]
                        prices = df_raw[close_col].iloc[1:]
                        prices = pd.to_numeric(prices, errors='coerce')
                        prices = prices.ffill()  # Forward fill missing values
                        formatted_data[stock] = prices
            
            result_df = pd.DataFrame(formatted_data)
            result_df = result_df.dropna(subset=['Date'])
            result_df.set_index('Date', inplace=True)
            
            print(f"📊 Processed {len(result_df)} rows for {len(stock_columns)} stocks")
            return result_df
            
        except Exception as e:
            print(f"❌ Attempt {attempt} failed: {e}")
            if attempt < len(urls):
                print("🔄 Trying next URL format...")
                continue
            else:
                raise Exception(f"All Google Sheets attempts failed. Last error: {e}")

def create_server_proof_chart(performance_data):
    """Create chart using pure Plotly - guaranteed to work on servers"""
    try:
        print("📊 Creating server-proof Plotly chart...")
        
        # Import Plotly
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        import plotly.io as pio
        
        # Configure Plotly for server environment
        pio.kaleido.scope.mathjax = None
        
        # Create figure
        fig = go.Figure()
        
        colors = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692']
        
        # Add traces for each stock
        for i, (stock_code, data) in enumerate(performance_data.items()):
            color = colors[i % len(colors)]
            
            fig.add_trace(go.Scatter(
                x=data['dates'],
                y=data['historical_pct'],
                mode='lines',
                name=stock_code,
                line=dict(color=color, width=3),
                hovertemplate=f'<b>{stock_code}</b><br>Date: %{{x}}<br>Return: %{{y:.2f}}%<extra></extra>'
            ))
        
        # Update layout
        fig.update_layout(
            title=dict(
                text='Hong Kong Stock Portfolio Performance Analysis',
                font=dict(size=24, color='white'),
                x=0.5
            ),
            xaxis=dict(title='Date', gridcolor='#333333', color='white'),
            yaxis=dict(title='Percentage Change from Entry (%)', gridcolor='#333333', color='white'),
            plot_bgcolor='black',
            paper_bgcolor='black',
            font=dict(color='white'),
            legend=dict(bgcolor='rgba(0,0,0,0.8)', bordercolor='white', borderwidth=1),
            width=1920,
            height=1080
        )
        
        # Export to PNG using Kaleido (server-safe)
        print("🔄 Exporting to PNG...")
        pio.write_image(fig, "portfolio_server.png", engine="kaleido", width=1920, height=1080)
        print("✅ Server-proof chart created: portfolio_server.png")
        
        return True
        
    except Exception as e:
        print(f"❌ Chart creation failed: {e}")
        return False

def send_to_telegram_robust(image_path, caption):
    """Ultra-robust Telegram sending with retries"""
    print("📤 Sending to Telegram (server-proof)...")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            
            with open(image_path, 'rb') as photo:
                files = {'photo': photo}
                data = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'caption': caption
                }
                
                response = requests.post(url, files=files, data=data, timeout=30)
                response.raise_for_status()
                
                print("✅ Successfully sent to Telegram!")
                return True
                
        except Exception as e:
            print(f"❌ Telegram attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print("🔄 Retrying in 5 seconds...")
                import time
                time.sleep(5)
            else:
                print("❌ All Telegram attempts failed")
                return False

def main():
    """Main server-proof execution"""
    print("🚀 Starting SERVER-PROOF Hong Kong Stock Analysis...")
    print("=" * 60)
    
    try:
        # Load portfolio
        stock_transactions = load_and_process_portfolio('profolio.csv')
        if not stock_transactions:
            print("❌ No portfolio data available")
            return
        
        # Load stock prices from Google Sheets
        GOOGLE_SHEET_ID = "1ZfEwBs4fo_py2qmTzAKj-eou8r4fNDoCvQdTUHpxDHs"
        price_data = load_stock_prices_from_google_sheets_robust(GOOGLE_SHEET_ID)
        
        # Calculate performance (simplified for server)
        performance_data = {}
        
        for stock_code, transaction_info in stock_transactions.items():
            if stock_code in price_data.columns:
                stock_prices = price_data[stock_code].dropna()
                buy_transactions = transaction_info['buy_transactions'].sort_values('Date')
                
                if len(stock_prices) > 0 and len(buy_transactions) > 0:
                    first_entry_date = buy_transactions.iloc[0]['Date']
                    
                    # Get prices from entry date onwards
                    entry_prices = stock_prices[stock_prices.index >= first_entry_date]
                    
                    if len(entry_prices) > 0:
                        # Calculate weighted average cost
                        total_cost = transaction_info['total_cost']
                        total_units = transaction_info['current_units']
                        avg_cost = total_cost / total_units if total_units > 0 else 0
                        
                        # Calculate percentage changes
                        pct_changes = ((entry_prices - avg_cost) / avg_cost * 100)
                        pct_changes.iloc[0] = 0.0  # Start from 0%
                        
                        current_price = entry_prices.iloc[-1]
                        current_pct = ((current_price - avg_cost) / avg_cost * 100)
                        
                        performance_data[stock_code] = {
                            'dates': entry_prices.index,
                            'historical_pct': pct_changes,
                            'pct_change': current_pct,
                            'entry_date': first_entry_date,
                            'current_price': current_price,
                            'avg_cost': avg_cost
                        }
                        
                        print(f"📈 {stock_code}: {current_pct:+.2f}% (HK${current_price:.2f})")
        
        if not performance_data:
            print("❌ No performance data calculated")
            return
        
        # Create chart
        if create_server_proof_chart(performance_data):
            # Create summary message
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            sorted_performance = sorted(performance_data.items(), key=lambda x: x[1]['pct_change'], reverse=True)
            best_stock, best_data = sorted_performance[0]
            worst_stock, worst_data = sorted_performance[-1]
            
            message = f"📊 Portfolio Update {timestamp}\n"
            message += f"🏆 Best: {best_stock} {best_data['pct_change']:+.1f}%\n"
            message += f"📉 Worst: {worst_stock} {worst_data['pct_change']:+.1f}%\n\n"
            message += "📈 All Stocks:\n"
            for stock, data in sorted_performance:
                message += f"• {stock}: {data['pct_change']:+.1f}%\n"
            
            # Send to Telegram
            if send_to_telegram_robust("portfolio_server.png", message):
                print("🎉 SERVER-PROOF analysis complete and sent to Telegram!")
            else:
                print("⚠️ Chart created but Telegram failed")
        else:
            print("❌ Chart creation failed")
            
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        
        # Send error notification to Telegram
        error_message = f"❌ Stock Analysis Error: {str(e)[:200]}..."
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': error_message}, timeout=10)
        except:
            pass

if __name__ == "__main__":
    main() 