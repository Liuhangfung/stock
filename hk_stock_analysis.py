import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from collections import defaultdict
import re
import os
import requests

def clean_currency_value(value):
    """Clean currency values by removing $ and , symbols"""
    if pd.isna(value) or value == '':
        return 0
    if isinstance(value, str):
        # Remove $ and , symbols, handle negative values in parentheses
        cleaned = value.replace('$', '').replace(',', '').strip()
        if cleaned.startswith('(') and cleaned.endswith(')'):
            cleaned = '-' + cleaned[1:-1]
        try:
            return float(cleaned)
        except:
            return 0
    return float(value)

def parse_date(date_str):
    """Parse date string in various formats"""
    if pd.isna(date_str):
        return None
    
    date_str = str(date_str).strip()
    
    # Try different date formats
    formats = ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y']
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except:
            continue
    
    return None

def load_and_process_portfolio(portfolio_file):
    """Load and process portfolio data to get all buy/sell transactions"""
    df = pd.read_csv(portfolio_file)
    
    # Clean the data
    df['Date'] = df['Date'].apply(parse_date)
    df['Transacted Price (per unit)'] = df['Transacted Price (per unit)'].apply(clean_currency_value)
    df['Transacted Units'] = df['Transacted Units'].apply(lambda x: float(x) if pd.notna(x) else 0)
    df['Cumulative Units'] = df['Cumulative Units'].apply(lambda x: float(x) if pd.notna(x) else 0)
    
    # Filter for Hong Kong stocks (assuming they have 4-digit stock codes)
    hk_stocks = df[df['Stock'].astype(str).str.match(r'^\d{4}$', na=False)]
    
    # Get all transactions for each stock
    stock_transactions = {}
    
    for stock in hk_stocks['Stock'].unique():
        stock_data = hk_stocks[hk_stocks['Stock'] == stock].sort_values('Date')
        
        # Only include stocks that currently have holdings
        latest_entry = stock_data.iloc[-1]
        if latest_entry['Cumulative Units'] > 0:
            # Get all buy transactions
            buy_transactions = stock_data[
                (stock_data['Type'] == 'Buy') & 
                (stock_data['Transacted Units'] > 0) &
                (stock_data['Transacted Price (per unit)'] > 0)
            ].copy()
            
            # Get all sell transactions
            sell_transactions = stock_data[
                (stock_data['Type'] == 'Sell') & 
                (stock_data['Transacted Units'] > 0) &
                (stock_data['Transacted Price (per unit)'] > 0)
            ].copy()
            
            # Get all transactions (buy + sell) for markers
            all_transactions = stock_data[
                (stock_data['Type'].isin(['Buy', 'Sell'])) & 
                (stock_data['Transacted Units'] > 0) &
                (stock_data['Transacted Price (per unit)'] > 0)
            ].copy()
            
            if len(buy_transactions) > 0:
                stock_transactions[str(stock)] = {
                    'buy_transactions': buy_transactions,
                    'sell_transactions': sell_transactions,
                    'all_transactions': all_transactions,
                    'current_units': latest_entry['Cumulative Units']
                }
    
    return stock_transactions

def load_stock_prices_from_google_sheets(sheet_id):
    """Load stock data from public Google Sheets"""
    import requests
    from io import StringIO
    
    print("Loading stock price data from Google Sheets...")
    
    try:
        # Download the sheet
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
        response = requests.get(url)
        
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")
        
        # Parse the raw data
        df_raw = pd.read_csv(StringIO(response.text))
        
        stock_columns = ['9988', '0388', '0823', '3690', '2700', '0728', '3329']
        
        # Extract date from the first stock column (9988)
        dates = df_raw['9988'].iloc[1:]  # Skip header row
        dates = pd.to_datetime(dates, format='%Y/%m/%d', errors='coerce')
        
        # Create the formatted dataframe
        formatted_data = {'Date': dates}
        
        # Extract prices for each stock
        for stock in stock_columns:
            if stock in df_raw.columns:
                # Get the Close column (next column after stock name)
                close_col_idx = df_raw.columns.get_loc(stock) + 1
                if close_col_idx < len(df_raw.columns):
                    close_col = df_raw.columns[close_col_idx]
                    prices = df_raw[close_col].iloc[1:]  # Skip header row
                    
                    # Convert to numeric, handle 'NA' and empty values
                    prices = pd.to_numeric(prices, errors='coerce')
                    
                    # Forward fill ALL missing values (no change = use previous price)
                    prices = prices.ffill()
                    
                    formatted_data[stock] = prices
        
        # Create final dataframe
        result_df = pd.DataFrame(formatted_data)
        result_df = result_df.dropna(subset=['Date'])
        result_df.set_index('Date', inplace=True)
        
        print(f"✅ Loaded {len(result_df)} rows from Google Sheets")
        return result_df
        
    except Exception as e:
        print(f"❌ Google Sheets failed ({e}), using local CSV")
        return load_stock_prices_fallback()

def load_stock_prices_fallback():
    """Fallback to local CSV if Google Sheets fails"""
    df = pd.read_csv('stock_data.csv')
    df['Date'] = pd.to_datetime(df['Date'], format='%Y/%m/%d', errors='coerce')
    df.set_index('Date', inplace=True)
    price_columns = [col for col in df.columns if col != 'Date']
    for col in price_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        # Forward fill ALL missing values (no change = use previous price)
        df[col] = df[col].ffill()
    return df

def calculate_performance_from_entries(stock_transactions, price_data):
    """Calculate performance with proper 加倉 logic - weighted average cost basis"""
    performance_data = {}
    
    for stock_code, transaction_info in stock_transactions.items():
        if stock_code in price_data.columns:
            stock_prices = price_data[stock_code].dropna()
            buy_transactions = transaction_info['buy_transactions'].sort_values('Date')
            all_transactions = transaction_info['all_transactions']
            
            if len(stock_prices) > 0 and len(buy_transactions) > 0:
                # Get the first entry date
                first_entry_date = buy_transactions.iloc[0]['Date']
                if isinstance(first_entry_date, str):
                    first_entry_date = pd.to_datetime(first_entry_date)
                else:
                    first_entry_date = pd.Timestamp(first_entry_date)
                
                # Get prices from the first entry date onwards
                prices_from_entry = stock_prices[stock_prices.index >= first_entry_date]
                
                if len(prices_from_entry) > 0:
                    # Calculate dynamic returns that change when you 加倉
                    # Your return changes as your average cost changes with new purchases
                    
                    performance_series = []
                    dates_series = []
                    
                    # Track running cost and units as ALL transactions are made (buys AND sells)
                    running_cost = 0
                    running_units = 0
                    current_avg_cost = 0
                    
                    for price_date, market_price in prices_from_entry.items():
                        # Check for any new transactions (buys + sells) on or before this date
                        transactions_up_to_date = all_transactions[
                            pd.to_datetime(all_transactions['Date']) <= price_date
                        ].sort_values('Date')
                        
                        # Recalculate position up to this date (process buys and sells)
                        temp_cost = 0
                        temp_units = 0
                        
                        for _, transaction in transactions_up_to_date.iterrows():
                            if transaction['Type'] == 'Buy':
                                # Add to position
                                purchase_cost = transaction['Transacted Units'] * transaction['Transacted Price (per unit)']
                                temp_cost += purchase_cost
                                temp_units += transaction['Transacted Units']
                            elif transaction['Type'] == 'Sell':
                                # Remove from position (proportionally reduce cost)
                                if temp_units > 0:
                                    cost_per_unit = temp_cost / temp_units
                                    sell_cost = cost_per_unit * transaction['Transacted Units']
                                    temp_cost -= sell_cost
                                    temp_units -= transaction['Transacted Units']
                        
                        # Update current average cost and calculate return
                        if temp_units > 0:
                            current_avg_cost = temp_cost / temp_units
                            current_return = ((market_price - current_avg_cost) / current_avg_cost) * 100
                            
                            # Cap extreme returns to prevent chart scaling issues
                            if current_return > 1000:  # Cap at 1000%
                                current_return = 1000
                            elif current_return < -100:  # Cap at -100%
                                current_return = -100
                                
                            performance_series.append(current_return)
                            dates_series.append(price_date)
                        elif len(performance_series) > 0:
                            # If no position, but we had one before, continue with 0%
                            performance_series.append(0.0)
                            dates_series.append(price_date)
                    
                    # Convert to pandas Series
                    if len(performance_series) > 0:
                        pct_changes = pd.Series(performance_series, index=dates_series)
                        # Force first point to be 0% (first purchase)
                        pct_changes.iloc[0] = 0.0
                    
                    # Calculate CORRECT weighted average cost accounting for buys AND sells
                    # Process all transactions chronologically to track running position
                    running_cost = 0
                    running_units = 0
                    
                    # Get all transactions (buys + sells) in chronological order
                    all_chronological = all_transactions.sort_values('Date')
                    
                    for _, transaction in all_chronological.iterrows():
                        if transaction['Type'] == 'Buy':
                            # Add to position
                            cost = transaction['Transacted Units'] * transaction['Transacted Price (per unit)']
                            running_cost += cost
                            running_units += transaction['Transacted Units']
                        elif transaction['Type'] == 'Sell':
                            # Remove from position (proportionally reduce cost)
                            if running_units > 0:
                                cost_per_unit = running_cost / running_units
                                sell_cost = cost_per_unit * transaction['Transacted Units']
                                running_cost -= sell_cost
                                running_units -= transaction['Transacted Units']
                    
                    weighted_avg_cost = running_cost / running_units if running_units > 0 else 0
                    
                    # Debug output for server troubleshooting
                    print(f"  {stock_code}: {running_units:,} units @ avg HK${weighted_avg_cost:.2f}")
                    
                    # Get current price and calculate current percentage
                    current_price = stock_prices.iloc[-1]
                    print(f"    Current market price: HK${current_price:.2f}")
                    if weighted_avg_cost > 0:
                        current_pct_change = ((current_price - weighted_avg_cost) / weighted_avg_cost) * 100
                    else:
                        current_pct_change = 0
                    
                    performance_data[stock_code] = {
                        'entry_price': weighted_avg_cost,  # Use weighted average cost
                        'transaction_price': weighted_avg_cost,  # Same as entry price now
                        'current_price': current_price,
                        'pct_change': current_pct_change,
                        'units': running_units,  # Use correctly calculated running units
                        'entry_date': first_entry_date,
                        'historical_pct': pct_changes,
                        'all_transactions': all_transactions,  # Add all transactions for markers
                        'dates': pct_changes.index,
                        'unrealized_pnl': (current_price - weighted_avg_cost) * running_units
                    }
    
    return performance_data

def create_performance_strip_html(performance_data, price_data):
    """Create independent HTML performance strip"""
    # Color palette for different stocks (same as chart)
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2']
    
    strip_html = """
    <div class="performance-strip">
    """
    
    for i, (stock_code, data) in enumerate(performance_data.items()):
        current_pct = data['pct_change']
        return_sign = "+" if current_pct >= 0 else ""
        entry_date_str = data['entry_date'].strftime('%d %b')
        
        # Calculate daily return change (how much your return % changed today)
        current_price = data['current_price']
        
        # Get yesterday's price to calculate yesterday's return
        stock_prices_for_stock = price_data[stock_code].dropna()
        if len(stock_prices_for_stock) >= 2:
            yesterday_price = stock_prices_for_stock.iloc[-2]
            weighted_avg_cost = data['entry_price']
            
            # Calculate yesterday's return %
            yesterday_return = ((yesterday_price - weighted_avg_cost) / weighted_avg_cost) * 100
            today_return = current_pct  # This is today's return %
            
            # Daily return change = today's return - yesterday's return
            daily_return_change = today_return - yesterday_return
            daily_sign = "+" if daily_return_change >= 0 else ""
            daily_change = f"{daily_sign}{daily_return_change:.2f}%"
        else:
            daily_change = "N/A"
        
        strip_html += f"""
        <div class="performance-item">
            <div class="main-row">
                <div class="return-pct">{return_sign}{current_pct:.2f}%</div>
                <div class="right-side">
                    <div class="daily-change">{daily_change}</div>
                    <div class="entry-date">from {data['entry_date'].strftime('%d %b')}</div>
                    <div class="entry-year">{data['entry_date'].strftime('%Y')}</div>
                </div>
            </div>
            <div class="info-row">
                <div class="stock-symbol">
                    <span class="color-line" style="background-color: {colors[i % len(colors)]};"></span>
                    {stock_code}
                </div>
            </div>
        </div>
        """
    
    strip_html += """
    </div>
    """
    
    return strip_html

# Telegram Bot Integration
TELEGRAM_BOT_TOKEN = "8405817372:AAGTdY0dZg3BfZKd9pgTTzXQ2HKKac12-o8"
TELEGRAM_CHAT_ID = "1051226560"

def take_screenshot_playwright(html_file):
    """Take screenshot using playwright"""
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            
            abs_path = os.path.abspath(html_file)
            file_url = f"file:///{abs_path.replace(os.sep, '/')}"
            
            print(f"📸 Taking screenshot...")
            page.goto(file_url)
            page.wait_for_timeout(5000)  # Wait for chart to load
            
            page.screenshot(path="portfolio_screenshot.png", full_page=True)
            browser.close()
            
            print("✅ Screenshot saved!")
            return True
            
    except ImportError:
        print("❌ Playwright not installed. Install with:")
        print("pip install playwright")
        print("playwright install chromium")
        return False
    except Exception as e:
        print(f"❌ Screenshot failed: {e}")
        return False

def send_to_telegram(image_path, caption):
    """Send screenshot to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        
        with open(image_path, 'rb') as photo:
            files = {'photo': photo}
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'caption': caption
            }
            
            print(f"📤 Sending to Telegram...")
            response = requests.post(url, files=files, data=data)
            
            if response.status_code == 200:
                print("✅ Successfully sent to Telegram!")
                return True
            else:
                print(f"❌ Telegram error: {response.json()}")
                return False
                
    except Exception as e:
        print(f"❌ Send failed: {e}")
        return False

def create_performance_chart(performance_data):
    """Create an interactive performance chart starting from 0% at entry points"""
    
    # Create subplot
    fig = make_subplots(
        rows=1, cols=1,
        subplot_titles=None  # Remove subplot title to avoid duplication
    )
    
    # Color palette for different stocks
    colors = px.colors.qualitative.Set3
    
    # Add traces for each stock
    for i, (stock_code, data) in enumerate(performance_data.items()):
        color = colors[i % len(colors)]
        
        # Add the performance line starting from entry date at 0%
        fig.add_trace(
            go.Scatter(
                x=data['dates'],
                y=data['historical_pct'],
                mode='lines',
                name=f"{stock_code}",
                line=dict(color=color, width=2),
                hovertemplate=f"<b>{stock_code}</b><br>" +
                             "Date: %{x}<br>" +
                             "Change: %{y:.2f}%<br>" +
                             f"Entry: HK${data['entry_price']:.2f}<br>" +
                             f"Current: HK${data['current_price']:.2f}<br>" +
                             f"Units: {data['units']:,.0f}<br>" +
                             "<extra></extra>"
            )
        )
        
        # Add entry point marker at exactly 0%
        fig.add_trace(
            go.Scatter(
                x=[data['entry_date']],
                y=[0],
                mode='markers',
                name=f"{stock_code} Entry",
                marker=dict(
                    color=color,
                    size=10,
                    symbol='circle',
                    line=dict(color='white', width=2)
                ),
                showlegend=False,
                hovertemplate=f"<b>{stock_code} Entry Point</b><br>" +
                             f"Date: {data['entry_date'].strftime('%Y-%m-%d')}<br>" +
                             f"Price: HK${data['entry_price']:.2f}<br>" +
                             "Change: 0.00%<br>" +
                             "<extra></extra>"
            )
        )
        
        # Smart positioning: avoid overlap but keep labels close to their lines
        last_date = data['dates'][-1]
        last_performance = data['historical_pct'].iloc[-1]
        
        # Collect all line end positions to detect overlaps
        all_end_positions = []
        for code, perf_data in performance_data.items():
            end_y = perf_data['historical_pct'].iloc[-1]
            all_end_positions.append((code, end_y))
        
        # Sort by y position and adjust overlapping labels
        sorted_positions = sorted(all_end_positions, key=lambda x: x[1], reverse=True)
        
        # Find current stock's adjusted position
        for idx, (code, orig_y) in enumerate(sorted_positions):
            if code == stock_code:
                # If labels would be too close (within 8% range), spread them out
                min_spacing = 8  # Minimum spacing between labels
                adjusted_y = orig_y
                
                # Check for conflicts with previous labels and adjust
                for prev_idx in range(idx):
                    prev_code, prev_y = sorted_positions[prev_idx]
                    if abs(adjusted_y - prev_y) < min_spacing:
                        # Adjust position to maintain minimum spacing
                        adjusted_y = prev_y - min_spacing
                
                label_y = adjusted_y
                break
        
        # Short dotted line if label was moved
        if abs(label_y - last_performance) > 2:  # Only add line if label moved significantly
            fig.add_trace(
                go.Scatter(
                    x=[last_date, last_date + pd.Timedelta(days=8)],
                    y=[last_performance, label_y],
                    mode='lines',
                    line=dict(color=color, width=1, dash='dot'),
                    showlegend=False,
                    hoverinfo='skip'
                )
            )
            label_x = last_date + pd.Timedelta(days=10)
        else:
            # No line needed, label stays at line end
            label_x = last_date
        
        # Add stock label
        fig.add_trace(
            go.Scatter(
                x=[label_x],
                y=[label_y],
                mode='text',
                text=[stock_code],
                textposition='middle right',
                textfont=dict(
                    color=color,
                    size=12,
                    family="Arial"
                ),
                showlegend=False,
                hoverinfo='skip'
            )
        )
        
        # Add transaction markers (加倉/減倉)
        if 'all_transactions' in data and len(data['all_transactions']) > 0:
            for _, transaction in data['all_transactions'].iterrows():
                transaction_date = pd.to_datetime(transaction['Date'])
                
                # Skip if transaction is before our chart start date
                if transaction_date < data['entry_date']:
                    continue
                
                # Find the corresponding percentage on that date
                try:
                    # Find the closest date in our price data
                    price_data_dates = pd.to_datetime(data['dates'])
                    
                    # Check if transaction date is beyond our price data
                    if transaction_date > price_data_dates.max():
                        continue  # Skip future transactions beyond price data
                    
                    closest_date_idx = np.abs(price_data_dates - transaction_date).argmin()
                    transaction_pct = data['historical_pct'].iloc[closest_date_idx]
                except Exception as e:
                    continue  # Skip if we can't find the date
                
                # Determine marker style based on transaction type
                if transaction['Type'] == 'Buy':
                    marker_symbol = 'circle'
                    marker_color = 'rgba(0, 255, 0, 0.7)'  # Green with transparency
                    marker_size = 8  # Small size
                    action_text = f"加倉 +{transaction['Transacted Units']:,.0f}"
                else:  # Sell
                    marker_symbol = 'circle'
                    marker_color = 'rgba(255, 0, 0, 0.7)'  # Red with transparency
                    marker_size = 8  # Small size
                    action_text = f"減倉 -{transaction['Transacted Units']:,.0f}"
                
                # Add transaction marker
                fig.add_trace(
                    go.Scatter(
                        x=[transaction_date],
                        y=[transaction_pct],
                        mode='markers',
                        name=f"{stock_code} {transaction['Type']}",
                        marker=dict(
                            color=marker_color,
                            size=marker_size,
                            symbol=marker_symbol
                        ),
                        showlegend=False,
                        hovertemplate=f"<b>{stock_code} {action_text}</b><br>" +
                                     f"Date: {transaction_date.strftime('%Y-%m-%d')}<br>" +
                                     f"Price: HK${transaction['Transacted Price (per unit)']:.2f}<br>" +
                                     f"Units: {transaction['Transacted Units']:,.0f}<br>" +
                                     f"Performance: {transaction_pct:.2f}%<br>" +
                                     "<extra></extra>"
                    )
                )
    
    # Add horizontal line at 0%
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.7, line_width=2)
    
    # Update layout to match the reference style
    fig.update_layout(
        title='',  # Remove title since we have the performance strip
        xaxis_title="Date",
        yaxis_title="Percentage Change from Entry (%)",
        plot_bgcolor='black',
        paper_bgcolor='black',
        font=dict(color='white'),
        xaxis=dict(
            gridcolor='#333333',
            showgrid=True,
            color='white'
        ),
        yaxis=dict(
            gridcolor='#333333',
            showgrid=True,
            color='white',
            tickformat='.1f',
            zeroline=True,
            zerolinecolor='gray',
            zerolinewidth=2
        ),
        showlegend=False,  # Remove the legend box completely
        hovermode='x unified',
        height=700,
        margin=dict(t=50, b=100, l=80, r=80)  # Normal right margin
    )
    
    return fig

def create_summary_chart(performance_data):
    """Create a summary bar chart showing current performance"""
    stocks = list(performance_data.keys())
    pct_changes = [data['pct_change'] for data in performance_data.values()]
    
    # Color bars based on positive/negative performance
    colors = ['#00ff88' if x >= 0 else '#ff4444' for x in pct_changes]
    
    fig = go.Figure(data=[
        go.Bar(
            x=stocks,
            y=pct_changes,
            marker_color=colors,
            text=[f"{x:+.1f}%" for x in pct_changes],
            textposition='outside',
            hovertemplate="<b>%{x}</b><br>Change: %{y:.2f}%<extra></extra>"
        )
    ])
    
    fig.update_layout(
        title={
            'text': 'Current Performance Summary - % Change from Entry',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 16, 'color': 'white'}
        },
        xaxis_title="Stock Code",
        yaxis_title="Percentage Change (%)",
        plot_bgcolor='black',
        paper_bgcolor='black',
        font=dict(color='white'),
        xaxis=dict(color='white'),
        yaxis=dict(
            color='white',
            tickformat='.1f',
            zeroline=True,
            zerolinecolor='gray',
            zerolinewidth=2
        ),
        height=400
    )
    
    return fig

def generate_summary_table(performance_data):
    """Generate a summary table of current performance"""
    summary_data = []
    
    for stock_code, data in performance_data.items():
        summary_data.append({
            'Stock': stock_code,
            'Entry Price (HK$)': f"{data['entry_price']:.2f}",
            'Current Price (HK$)': f"{data['current_price']:.2f}",
            'Units': f"{data['units']:,.0f}",
            'Change (%)': f"{data['pct_change']:+.2f}%",
            'Unrealized P&L (HK$)': f"{data['unrealized_pnl']:+,.2f}",
            'Entry Date': data['entry_date'].strftime('%Y-%m-%d') if data['entry_date'] else 'N/A'
        })
    
    return pd.DataFrame(summary_data)

def main():
    """Main function to run the analysis"""
    print("Loading portfolio transactions...")
    stock_transactions = load_and_process_portfolio('profolio.csv')
    
    if not stock_transactions:
        print("No current Hong Kong stock holdings found!")
        return
    
    print(f"Found {len(stock_transactions)} Hong Kong stocks with current holdings:")
    for stock, info in stock_transactions.items():
        buy_txns = info['buy_transactions']
        avg_price = (buy_txns['Transacted Units'] * buy_txns['Transacted Price (per unit)']).sum() / buy_txns['Transacted Units'].sum()
        earliest_date = buy_txns['Date'].min().strftime('%Y-%m-%d')
        print(f"  {stock}: {info['current_units']:,.0f} units @ avg HK${avg_price:.2f} (entry: {earliest_date})")
    
    print("\nLoading stock price data...")
    # Load stock price data - try local CSV first, then Google Sheets
    if os.path.exists('stock_data.csv'):
        print("📁 Using local stock_data.csv")
        price_data = load_stock_prices_fallback()
    else:
        print("🌐 Local CSV not found, using Google Sheets...")
        GOOGLE_SHEET_ID = "1ZfEwBs4fo_py2qmTzAKj-eou8r4fNDoCvQdTUHpxDHs"
        price_data = load_stock_prices_from_google_sheets(GOOGLE_SHEET_ID)
    
    print("Calculating performance from YOUR entry dates...")
    performance_data = calculate_performance_from_entries(stock_transactions, price_data)
    
    if not performance_data:
        print("No performance data could be calculated!")
        return
    
    print(f"Performance calculated for {len(performance_data)} stocks")
    
    # Create charts
    print("Creating performance chart (each line starts from YOUR entry date)...")
    performance_chart = create_performance_chart(performance_data)
    
    print("Creating summary chart...")
    summary_chart = create_summary_chart(performance_data)
    
    # Generate summary table
    summary_df = generate_summary_table(performance_data)
    
    # Create HTML report
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Hong Kong Stock Portfolio Analysis</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {{
                background-color: black;
                color: white;
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 0;
            }}
            
            .performance-strip {{
                background-color: #000000;
                display: flex;
                justify-content: flex-start;
                align-items: center;
                padding: 12px 20px;
                margin: 0;
                width: 100%;
                box-sizing: border-box;
                gap: 30px;
            }}
            
            .performance-item {{
                display: flex;
                flex-direction: column;
                align-items: flex-start;
                text-align: left;
                flex: 0 0 auto;
                min-width: 120px;
                padding: 0;
            }}
            
            .main-row {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                width: 100%;
                margin-bottom: 3px;
            }}
            
            .info-row {{
                display: flex;
                justify-content: flex-start;
                width: 100%;
            }}
            
            .return-pct {{
                font-size: 48px;
                font-weight: bold;
                color: white;
                line-height: 0.9;
            }}
            
            .right-side {{
                display: flex;
                flex-direction: column;
                align-items: flex-end;
                text-align: right;
            }}
            
            .daily-change {{
                font-size: 14px;
                font-weight: normal;
                color: #ff4444;
                line-height: 1;
                margin-bottom: 2px;
            }}
            
            .entry-date {{
                font-size: 11px;
                color: #cccccc;
                line-height: 1;
                white-space: nowrap;
            }}
            
            .entry-year {{
                font-size: 11px;
                color: #cccccc;
                line-height: 1;
            }}
            
            .stock-symbol {{
                font-size: 12px;
                color: #cccccc;
                line-height: 1;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 5px;
            }}
            
            .color-line {{
                width: 15px;
                height: 3px;
                border-radius: 1px;
            }}
            
            .right-side {{
                display: flex;
                flex-direction: column;
                align-items: center;
                text-align: center;
            }}
            
            .main-content {{
                padding: 20px;
            }}
            .summary-table {{
                background-color: #1a1a1a;
                border-collapse: collapse;
                width: 100%;
                margin: 20px 0;
            }}
            .summary-table th, .summary-table td {{
                border: 1px solid #333;
                padding: 8px;
                text-align: right;
            }}
            .summary-table th {{
                background-color: #333;
            }}
            .positive {{ color: #00ff88; }}
            .negative {{ color: #ff4444; }}
            .neutral {{ color: white; }}
            h1, h2 {{ text-align: center; }}
            .note {{
                background-color: #1a1a1a;
                border: 1px solid #333;
                padding: 15px;
                margin: 20px 0;
                border-radius: 5px;
            }}
        </style>
    </head>
          <body>
        <div class="main-content">
          <h1 style="text-align: left; margin-bottom: 5px;">Hong Kong Stock Portfolio Performance Analysis</h1>
          <p style="text-align: left; margin-top: 0; margin-bottom: 20px;">Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        {create_performance_strip_html(performance_data, price_data)}
        <div class="chart-content">
        
        <div id="performance-chart"></div>

        
        <script>
            var performanceChart = {performance_chart.to_json()};
            Plotly.newPlot('performance-chart', performanceChart.data, performanceChart.layout);
        </script>
        </div>
        </div>
    </body>
    </html>
    """
    
    # Save HTML file
    with open('hk_stock_analysis.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print("\n" + "="*60)
    print("ANALYSIS COMPLETE!")
    print("="*60)
    
    # Calculate total P&L
    total_pnl = sum(data['unrealized_pnl'] for data in performance_data.values())
    print(f"Total Portfolio Value Change: HK${total_pnl:+,.2f}")
    print(f"Number of Holdings: {len(performance_data)}")
    print("\nYour Winning Stocks:")
    
    # Sort by percentage change
    sorted_performance = sorted(performance_data.items(), 
                              key=lambda x: x[1]['pct_change'], 
                              reverse=True)
    
    winners = [(stock, data) for stock, data in sorted_performance if data['pct_change'] >= 0]
    losers = [(stock, data) for stock, data in sorted_performance if data['pct_change'] < 0]
    
    if winners:
        for i, (stock, data) in enumerate(winners):
            print(f"  {i+1}. {stock}: +{data['pct_change']:.2f}% (HK${data['unrealized_pnl']:+,.2f})")
    else:
        print("  No winning stocks currently")
    
    print("\nYour Losing Stocks:")
    if losers:
        for i, (stock, data) in enumerate(losers):
            print(f"  {i+1}. {stock}: {data['pct_change']:.2f}% (HK${data['unrealized_pnl']:+,.2f})")
    else:
        print("  No losing stocks currently")
    
    print(f"\nDetailed analysis saved to: hk_stock_analysis.html")
    print("✅ Each stock line now starts exactly from your entry date at 0%!")
    print("📈 Positive % = You're winning | 📉 Negative % = You're losing")
    
    # Telegram Integration - Take screenshot and send
    print("\n📱 TELEGRAM UPDATE:")
    print("=" * 30)
    
    # Take screenshot
    if take_screenshot_playwright("hk_stock_analysis.html"):
        # Create message with current performance summary
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Get top performer and worst performer
        sorted_performance = sorted(performance_data.items(), key=lambda x: x[1]['pct_change'], reverse=True)
        best_stock, best_data = sorted_performance[0] if sorted_performance else ("N/A", {"pct_change": 0})
        worst_stock, worst_data = sorted_performance[-1] if sorted_performance else ("N/A", {"pct_change": 0})
        
        message = f"📊 Portfolio Update {timestamp}"
        
        # Send to Telegram
        if send_to_telegram("portfolio_screenshot.png", message):
            print("🎉 Daily update sent to Telegram successfully!")
        else:
            print("⚠️  Screenshot saved but Telegram send failed")
    else:
        print("❌ Screenshot failed - no Telegram update")

if __name__ == "__main__":
    main() 