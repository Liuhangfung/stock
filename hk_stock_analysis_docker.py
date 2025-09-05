#!/usr/bin/env python3
"""
Docker-Specific Hong Kong Stock Analysis
========================================

This version is specifically designed for Docker with:
1. Direct Plotly image export using kaleido
2. Proper timeout handling to prevent hanging
3. Virtual display support
4. Guaranteed image generation for Telegram

"""

import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime
import warnings
import signal
import threading
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
warnings.filterwarnings('ignore')

# Telegram Configuration
TELEGRAM_BOT_TOKEN = "8324596740:AAH7j1rsRUddl0J-81vdeXoVFL666Y4MRYU"
TELEGRAM_CHAT_ID = "1051226560"

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

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
                    'Transacted Units': units,
                    'Transacted Price (per unit)': price
                }
                
                stock_transactions[stock_code]['all_transactions'].append(transaction_data)
                
                if transaction_type == 'Buy' and units > 0:
                    stock_transactions[stock_code]['buy_transactions'].append(transaction_data)
                    stock_transactions[stock_code]['current_units'] += units
                    stock_transactions[stock_code]['total_cost'] += units * price
                elif transaction_type == 'Sell' and units > 0:
                    stock_transactions[stock_code]['sell_transactions'].append(transaction_data)
                    # Note: We don't update current_units/total_cost here since the 
                    # correct calculation is done in calculate_performance_from_entries()
        
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

def load_stock_prices_from_google_sheets(sheet_id):
    """Load stock data from Google Sheets with timeout"""
    print("🌐 Loading data from Google Sheets...")
    
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
        
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        from io import StringIO
        df_raw = pd.read_csv(StringIO(response.text))
        
        stock_columns = ['9988', '0388', '0823', '3690', '2700', '0728', '3329']
        
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
                    prices = prices.ffill()
                    formatted_data[stock] = prices
        
        result_df = pd.DataFrame(formatted_data)
        result_df = result_df.dropna(subset=['Date'])
        result_df.set_index('Date', inplace=True)
        
        print(f"✅ Loaded {len(result_df)} rows from Google Sheets")
        return result_df
        
    except Exception as e:
        raise Exception(f"Google Sheets loading failed: {e}")

def calculate_performance_from_entries(stock_transactions, price_data):
    """Calculate performance with CORRECT weighted average cost basis (copied from working version)"""
    performance_data = {}
    
    for stock_code, transaction_info in stock_transactions.items():
        if stock_code in price_data.columns:
            stock_prices = price_data[stock_code].dropna()
            all_transactions = transaction_info['all_transactions']
            
            if len(stock_prices) > 0 and len(all_transactions) > 0:
                # Get first entry date
                buy_transactions = all_transactions[all_transactions['Type'] == 'Buy']
                if len(buy_transactions) > 0:
                    first_entry_date = pd.to_datetime(buy_transactions.iloc[0]['Date'])
                    
                    # Get price data from first entry onwards
                    entry_prices = stock_prices[stock_prices.index >= first_entry_date]
                    
                    if len(entry_prices) > 0:
                        # Calculate dynamic percentage changes accounting for all transactions
                        performance_series = []
                        dates_series = []
                        
                        for price_date, market_price in entry_prices.items():
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
                        
                        # Get current price and calculate current percentage
                        current_price = stock_prices.iloc[-1]
                        if weighted_avg_cost > 0:
                            current_pct_change = ((current_price - weighted_avg_cost) / weighted_avg_cost) * 100
                        else:
                            current_pct_change = 0
                        
                        performance_data[stock_code] = {
                            'entry_price': weighted_avg_cost,
                            'current_price': current_price,
                            'pct_change': current_pct_change,
                            'units': running_units,
                            'entry_date': first_entry_date,
                            'historical_pct': pct_changes,
                            'dates': pct_changes.index,
                            'unrealized_pnl': (current_price - weighted_avg_cost) * running_units
                        }
                        
                        print(f"📈 {stock_code}: {current_pct_change:+.2f}% (Avg: HK${weighted_avg_cost:.2f}, Current: HK${current_price:.2f})")
    
    return performance_data

def create_performance_strip_html(performance_data, price_data):
    """Create independent HTML performance strip"""
    # Color palette for different stocks (same as chart)
    colors = px.colors.qualitative.Set3
    
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

def create_performance_chart(performance_data):
    """Create an interactive performance chart starting from 0% at entry points"""
    
    # Create subplot
    from plotly.subplots import make_subplots
    import plotly.express as px
    import numpy as np
    
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

def create_plotly_html_with_strip(performance_data, price_data):
    """Create complete HTML with performance strip and chart"""
    
    # Create the chart
    performance_chart = create_performance_chart(performance_data)
    
    # Create HTML content with performance strip
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
            
            .main-content {{
                padding: 20px;
            }}
            
            .chart-content {{
                padding: 0 20px;
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
    </body>
    </html>
    """
    
    return html_content

def create_plotly_image_with_embedded_strip(performance_data, price_data):
    """Create Plotly image with embedded performance strip using direct kaleido export"""
    print("📊 Creating Plotly image with embedded performance strip...")
    
    result = {'success': False, 'error': None}
    
    def create_image():
        try:
            import plotly.io as pio
            from plotly.subplots import make_subplots
            
            # Configure Plotly for Docker
            pio.kaleido.scope.mathjax = None
            
            # Create figure with performance strip embedded at the top
            fig = make_subplots(
                rows=2, cols=1,
                row_heights=[0.25, 0.75],  # 25% for title+strip, 75% for chart
                vertical_spacing=0.02,
                subplot_titles=("", "")
            )
            
            # Color palette for different stocks (same as reference)
            colors = px.colors.qualitative.Set3
            
            # Add title and analysis date (positioned above performance strip)
            fig.add_annotation(
                x=0.02, y=0.98,
                text="<b>Hong Kong Stock Portfolio Performance Analysis</b>",
                showarrow=False,
                font=dict(size=24, color='white', family='Arial'),
                xref="paper", yref="paper",
                xanchor='left'
            )
            
            # Add analysis date
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            fig.add_annotation(
                x=0.02, y=0.95,
                text=f"Analysis Date: {current_time}",
                showarrow=False,
                font=dict(size=12, color='white', family='Arial'),
                xref="paper", yref="paper",
                xanchor='left'
            )
            
            # Add performance strip as text annotations at the top (matching image layout)
            num_stocks = len(performance_data)
            for i, (stock_code, data) in enumerate(performance_data.items()):
                current_pct = data['pct_change']
                return_sign = "+" if current_pct >= 0 else ""
                
                # Calculate daily change
                stock_prices_for_stock = price_data[stock_code].dropna()
                if len(stock_prices_for_stock) >= 2:
                    yesterday_price = stock_prices_for_stock.iloc[-2]
                    weighted_avg_cost = data['entry_price']
                    yesterday_return = ((yesterday_price - weighted_avg_cost) / weighted_avg_cost) * 100
                    today_return = current_pct
                    daily_return_change = today_return - yesterday_return
                    daily_sign = "+" if daily_return_change >= 0 else ""
                    daily_change = f"{daily_sign}{daily_return_change:.2f}%"
                else:
                    daily_change = "+0.00%"
                
                # Position items evenly across the width
                x_pos = (i + 0.5) / num_stocks
                
                # Main percentage (large, white, bold) - moved down for title space
                fig.add_annotation(
                    x=x_pos, y=0.88,
                    text=f"<b>{return_sign}{current_pct:.2f}%</b>",
                    showarrow=False,
                    font=dict(size=32, color='white', family='Arial Black'),
                    xref="paper", yref="paper",
                    xanchor='center'
                )
                
                # Daily change (small, colored, top right)
                daily_color = '#ff4444' if daily_return_change < 0 else '#00ff88'
                fig.add_annotation(
                    x=x_pos + 0.06, y=0.91,
                    text=daily_change,
                    showarrow=False,
                    font=dict(size=12, color=daily_color),
                    xref="paper", yref="paper",
                    xanchor='left'
                )
                
                # Entry date (small, gray, below daily change)
                fig.add_annotation(
                    x=x_pos + 0.06, y=0.85,
                    text=f"from {data['entry_date'].strftime('%d %b')}",
                    showarrow=False,
                    font=dict(size=10, color='#cccccc'),
                    xref="paper", yref="paper",
                    xanchor='left'
                )
                
                # Entry year (small, gray, below date)
                fig.add_annotation(
                    x=x_pos + 0.06, y=0.81,
                    text=data['entry_date'].strftime('%Y'),
                    showarrow=False,
                    font=dict(size=10, color='#cccccc'),
                    xref="paper", yref="paper",
                    xanchor='left'
                )
                
                # Stock symbol (bottom, centered, with color)
                color = colors[i % len(colors)]
                fig.add_annotation(
                    x=x_pos, y=0.77,
                    text=stock_code,
                    showarrow=False,
                    font=dict(size=14, color=color, family='Arial'),
                    xref="paper", yref="paper",
                    xanchor='center'
                )
            
            # Add main chart traces
            for i, (stock_code, data) in enumerate(performance_data.items()):
                color = colors[i % len(colors)]
                
                # Add the performance line
                fig.add_trace(
                    go.Scatter(
                        x=data['dates'],
                        y=data['historical_pct'],
                        mode='lines',
                        name=stock_code,
                        line=dict(color=color, width=2),
                        hovertemplate=f"<b>{stock_code}</b><br>Date: %{{x}}<br>Return: %{{y:.2f}}%<extra></extra>",
                        showlegend=False
                    ),
                    row=2, col=1
                )
                
                # Add entry point marker
                fig.add_trace(
                    go.Scatter(
                        x=[data['entry_date']],
                        y=[0],
                        mode='markers',
                        marker=dict(color=color, size=8, symbol='circle'),
                        showlegend=False,
                        hovertemplate=f"<b>{stock_code} Entry</b><br>Date: {data['entry_date'].strftime('%Y-%m-%d')}<extra></extra>"
                    ),
                    row=2, col=1
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
                label_y = last_performance
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
                        ),
                        row=2, col=1
                    )
                    label_x = last_date + pd.Timedelta(days=10)
                else:
                    # No line needed, label stays at line end
                    label_x = last_date
                
                # Add stock label
                fig.add_annotation(
                    x=label_x,
                    y=label_y,
                    text=stock_code,
                    showarrow=False,
                    font=dict(size=12, color=color, family="Arial"),
                    xshift=15,
                    row=2, col=1
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
                            ),
                            row=2, col=1
                        )
            
            # Add horizontal line at 0%
            fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.7, row=2, col=1)
            
            # Update layout to match reference style exactly
            fig.update_layout(
                title="",
                plot_bgcolor='black',
                paper_bgcolor='black',
                font=dict(color='white'),
                height=1080,
                width=1920,
                margin=dict(t=100, b=100, l=80, r=80),
                showlegend=False,
                hovermode='x unified'
            )
            
            # Update axes to match reference
            fig.update_xaxes(
                title="Date",
                gridcolor='#333333',
                showgrid=True,
                color='white',
                row=2, col=1
            )
            fig.update_yaxes(
                title="Percentage Change from Entry (%)",
                gridcolor='#333333',
                showgrid=True,
                color='white',
                tickformat='.1f',
                zeroline=True,
                zerolinecolor='gray',
                zerolinewidth=2,
                row=2, col=1
            )
            
            # Hide the top subplot axes
            fig.update_xaxes(visible=False, row=1, col=1)
            fig.update_yaxes(visible=False, row=1, col=1)
            
            # Export to PNG using kaleido
            print("🔄 Exporting with kaleido...")
            pio.write_image(fig, "portfolio_chart.png", engine="kaleido", width=1920, height=1080)
            result['success'] = True
            
        except Exception as e:
            result['error'] = str(e)
    
    # Run with timeout
    thread = threading.Thread(target=create_image)
    thread.daemon = True
    thread.start()
    thread.join(timeout=30)  # 30 second timeout
    
    if thread.is_alive():
        print("⚠️ Plotly export timed out")
        return False
    elif result['success']:
        print("✅ Plotly image with embedded strip created successfully!")
        return True
    else:
        print(f"❌ Plotly export failed: {result.get('error', 'Unknown error')}")
        return False

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
        print("❌ Playwright not installed")
        return False
    except Exception as e:
        print(f"❌ Screenshot failed: {e}")
        return False

def send_to_telegram(image_path, caption):
    """Send image to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        
        with open(image_path, 'rb') as photo:
            files = {'photo': photo}
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'caption': caption
            }
            
            print(f"📤 Sending to Telegram...")
            response = requests.post(url, files=files, data=data, timeout=30)
            
            if response.status_code == 200:
                print("✅ Successfully sent to Telegram!")
                return True
            else:
                print(f"❌ Telegram error: {response.json()}")
                return False
                
    except Exception as e:
        print(f"❌ Send failed: {e}")
        return False

def main():
    """Main Docker execution"""
    print("🐳 DOCKER Hong Kong Stock Analysis with Plotly Images")
    print("=" * 60)
    
    try:
        # Load portfolio
        stock_transactions = load_and_process_portfolio('profolio.csv')
        if not stock_transactions:
            print("❌ No portfolio data available")
            return
        
        # Load stock prices from Google Sheets
        GOOGLE_SHEET_ID = "1ZfEwBs4fo_py2qmTzAKj-eou8r4fNDoCvQdTUHpxDHs"
        price_data = load_stock_prices_from_google_sheets(GOOGLE_SHEET_ID)
        
        # Calculate performance
        performance_data = calculate_performance_from_entries(stock_transactions, price_data)
        
        if not performance_data:
            print("❌ No performance data calculated")
            return
        
        # Create Plotly image with embedded performance strip
        if create_plotly_image_with_embedded_strip(performance_data, price_data):
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
            
            message += "\n🐳 Generated in Docker with Plotly + Embedded Performance Strip"
            
            # Send to Telegram
            if send_to_telegram("portfolio_chart.png", message):
                print("🎉 DOCKER analysis complete - Beautiful Plotly chart with embedded performance strip sent to Telegram!")
            else:
                print("⚠️ Image created but Telegram failed")
        else:
            print("❌ Plotly image creation failed in Docker")
            
    except Exception as e:
        print(f"❌ DOCKER ERROR: {e}")

if __name__ == "__main__":
    main() 