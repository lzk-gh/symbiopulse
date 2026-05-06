import os
import sys
import platform
import subprocess

def build_executables():
    """Build standalone executables for the CLI and MCP Server using PyInstaller"""
    print(f"Building for {platform.system()}...")
    
    # Common PyInstaller arguments
    # --onefile: Create a single executable file
    # --noconfirm: Replace output directory without asking
    # --clean: Clean PyInstaller cache and remove temporary files before building
    common_args = [
        "pyinstaller",
        "--onefile",
        "--noconfirm",
        "--clean",
        "--log-level=INFO"
    ]
    
    # 1. Build CLI Binary (sym)
    print("\n--- Building CLI (sym) ---")
    cli_args = common_args + [
        "--name", "sym" + (".exe" if platform.system() == "Windows" else ""),
        "--console",
        "symbiopulse/interfaces/cli.py"
    ]
    subprocess.run(cli_args, check=True)
    
    # 2. Build MCP Server Binary (sym-mcp)
    print("\n--- Building MCP Server (sym-mcp) ---")
    mcp_args = common_args + [
        "--name", "sym-mcp" + (".exe" if platform.system() == "Windows" else ""),
        "--console",
        "symbiopulse/interfaces/mcp_server.py"
    ]
    subprocess.run(mcp_args, check=True)
    
    print("\n✅ Build complete! Executables are located in the 'dist' folder.")
    print("You can distribute these files to users who do not have Python installed.")

if __name__ == "__main__":
    build_executables()
