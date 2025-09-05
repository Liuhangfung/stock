#!/usr/bin/env python3
"""
Simple server runner for Gary's stock analysis
Just run: python run_server.py
"""

import subprocess
import sys
import os

def install_requirements():
    """Install required packages"""
    packages = [
        'pandas==2.1.3',
        'numpy==1.24.3', 
        'plotly==5.17.0',
        'requests==2.31.0',
        'openpyxl==3.1.2',
        'kaleido==0.2.1'
    ]
    
    print("📦 Installing required packages...")
    for package in packages:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
            print(f"✅ {package}")
        except subprocess.CalledProcessError:
            print(f"❌ Failed to install {package}")
            return False
    return True

def run_analysis():
    """Run the stock analysis"""
    print("\n🚀 Running Hong Kong Stock Analysis...")
    
    # Check if Docker version exists, otherwise use regular version
    if os.path.exists('hk_stock_analysis_docker.py'):
        script = 'hk_stock_analysis_docker.py'
        print("🐳 Using Docker version...")
    else:
        script = 'hk_stock_analysis.py'
        print("🐍 Using regular version...")
    
    try:
        subprocess.check_call([sys.executable, script])
        print("✅ Analysis complete!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Analysis failed: {e}")
        return False

if __name__ == "__main__":
    print("🎯 Gary's Hong Kong Stock Analysis Server Runner")
    print("=" * 50)
    
    # Install requirements
    if not install_requirements():
        print("❌ Failed to install requirements")
        sys.exit(1)
    
    # Run analysis
    if not run_analysis():
        print("❌ Analysis failed")
        sys.exit(1)
    
    print("🎉 All done! Check your Telegram for the chart!") 