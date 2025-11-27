// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {GluexGsmSwapper} from "contracts/evk-periphery/Swaps/GluexGsmSwapper.sol";
import {SwapVerifier} from "contracts/SwapVerifier.sol";
import {GluexGsmLiquidator} from "contracts/GluexGsmLiquidator.sol";
import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";

contract DeployGluexLiquidator is Script {
    address constant GLUEX_ROUTER = 0xe95F6EAeaE1E4d650576Af600b33D9F7e5f9f7fd;
    address constant GSM = 0xcb17105F6A7A75D1F1C91317a4621d9AaAfe96Fd;
    address constant EVC = 0xceAA7cdCD7dDBee8601127a9Abb17A974d613db4;
    address constant PYTH = 0xe9d69CdD6Fe41e7B621B4A688C5D1a68cB5c8ADc;

    function run() public {
        vm.startBroadcast(vm.envUint("DEPLOYER_PRIVATE_KEY"));
        
        address deployer = vm.addr(vm.envUint("DEPLOYER_PRIVATE_KEY"));

        SwapVerifier swapVerifier = new SwapVerifier();

        GluexGsmSwapper gluexGsmSwapper = new GluexGsmSwapper(EVC, deployer, GLUEX_ROUTER, GSM);

        GluexGsmLiquidator gluexGsmLiquidator = new GluexGsmLiquidator(deployer, address(gluexGsmSwapper), address(swapVerifier), EVC, PYTH);
        
        vm.stopBroadcast();

        console2.log("SwapVerifier: ", address(swapVerifier));
        console2.log("GluexGsmSwapper: ", address(gluexGsmSwapper));
        console2.log("GluexGsmLiquidator: ", address(gluexGsmLiquidator));
    }
}