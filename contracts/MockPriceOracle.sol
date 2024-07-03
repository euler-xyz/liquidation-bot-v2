// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.0;

import {IERC4626} from "./IEVault.sol";

contract MockPriceOracle {
    error PriceOracle_InvalidConfiguration();

    uint256 constant SPREAD_SCALE = 100;
    uint256 spread;
    mapping(address vault => address asset) resolvedVaults;
    mapping(address base => mapping(address quote => uint256)) price;

    function name() external pure returns (string memory) {
        return "MockPriceOracle";
    }

    function getQuote(uint256 inAmount, address base, address quote) external view returns (uint256) {
        (,,, uint256 midOut) = resolveOracle(inAmount, base, quote);
        return midOut;
    }

    function getQuotes(uint256 inAmount, address base, address quote)
        external
        view
        returns (uint256 bidOut, uint256 askOut)
    {
        (,,, uint256 midOut) = resolveOracle(inAmount, base, quote);

        if (spread > 0) {
            bidOut = midOut * (100 - spread / 2) / SPREAD_SCALE;
            askOut = midOut * (100 + spread / 2) / SPREAD_SCALE;
        } else {
            bidOut = askOut = midOut;
        }
    }

    ///// Mock functions

    function setSpread(uint256 newSpread) external {
        spread = newSpread;
    }

    function setResolvedVault(address vault, bool set) external {
        address asset = set ? IERC4626(vault).asset() : address(0);
        resolvedVaults[vault] = asset;
    }

    function setPrice(address base, address quote, uint256 newPrice) external {
        price[base][quote] = newPrice;
    }

    function resolveOracle(uint256 inAmount, address base, address quote)
        public
        view
        returns (uint256, /* resolvedAmount */ address, /* base */ address, /* quote */ uint256 /* outAmount */ )
    {
        if (base == quote) return (inAmount, base, quote, inAmount);

        uint256 p = price[base][quote];
        if (p != 0) {
            return (inAmount, base, quote, inAmount * p / 1e18);
        }

        address baseAsset = resolvedVaults[base];
        if (baseAsset != address(0)) {
            inAmount = IERC4626(base).convertToAssets(inAmount);
            return resolveOracle(inAmount, baseAsset, quote);
        }

        revert PriceOracle_InvalidConfiguration();
    }
}
