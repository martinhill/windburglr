#!/bin/bash

# WindBurglr Development Setup Script
# This script helps set up the development environment using Nix

set -e

echo "🚀 Setting up WindBurglr development environment..."

# Check if Nix is installed
if ! command -v nix &> /dev/null; then
    echo "❌ Nix is not installed. Please install Nix first:"
    echo "   curl -L https://nixos.org/nix/install | sh"
    exit 1
fi

# Check if flakes are enabled
if ! nix flake --help &> /dev/null; then
    echo "❌ Nix flakes are not enabled. Please enable them:"
    echo "   echo 'experimental-features = nix-command flakes' >> ~/.config/nix/nix.conf"
    exit 1
fi

# Check if direnv is installed (optional)
if command -v direnv &> /dev/null; then
    echo "✅ direnv is installed"
    if [ ! -f ".envrc" ]; then
        echo "use flake" > .envrc
    fi
    direnv allow
else
    echo "ℹ️  direnv not found. You can install it for automatic environment activation:"
    echo "   nix-env -iA nixpkgs.direnv"
fi

echo "✅ Development environment configured!"
echo ""
echo "To start developing:"
echo "  nix develop"
echo ""
echo "Or if using direnv:"
echo "  cd . && direnv allow"
echo ""
echo "Then run:"
echo "  ./start.sh          # Start the application"
echo "  npm run dev         # Start frontend dev server"