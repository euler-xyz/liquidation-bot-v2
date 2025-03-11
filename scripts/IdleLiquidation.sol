// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.24;

import {console} from "forge-std/Test.sol";
import {Script} from "forge-std/Script.sol";

import {IEVault, IERC20, ILiquidation} from "../contracts/IEVault.sol";
import {IEVC} from "../contracts/IEVC.sol";

contract IdleLiquidation is Script {
    address constant USDC_VAULT = 0x166d8B62E1748D04eDf39d0078F1Fe4aA01D475E;
    address constant USDC = 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48;

    address constant IDLE_VAULT = 0xd820C8129a853a04dC7e42C64aE62509f531eE5A;
    address constant IDLE_ASSET = 0x45054c6753b4Bce40C5d54418DabC20b070F85bE;

    address constant EVC_ADDRESS = 0x0C9a3dd6b8F28529d72d7f9cE918D493519EE383;

    address constant VIOLATOR = 0xe0e6111985A78E99596FE8100c07Ba8a8403060F;
    address constant LIQUIDATOR = 0x8cbB534874bab83e44a7325973D2F04493359dF8;

    IEVault usdc_vault;
    IEVault idle_vault;

    IERC20 usdc;
    IERC20 idle;

    IEVC evc;

    function run() public {
        evc = IEVC(EVC_ADDRESS);

        usdc_vault = IEVault(USDC_VAULT);
        usdc = IERC20(USDC);

        idle_vault = IEVault(IDLE_VAULT);
        idle = IERC20(IDLE_ASSET);

        idle.approve(IDLE_VAULT, type(uint256).max);

        evc.enableController(USDC_VAULT, USDC_VAULT);
        evc.enableCollateral(IDLE_VAULT, IDLE_VAULT);

        (uint256 maxRepay, uint256 maxYield) = usdc_vault.checkLiquidation(LIQUIDATOR, VIOLATOR, IDLE_VAULT);

        idle_vault.withdraw(maxYield, address(this), address(this));
    }
}
