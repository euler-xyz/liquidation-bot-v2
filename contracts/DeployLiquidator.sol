// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";

import {Liquidator} from "./Liquidator.sol";

import "forge-std/console2.sol";

contract DeployLiquidator is Script {
    function run() public {
        uint256 deployerPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");

        address swapperAddress = 0x7813D94D8276fb1658e7fC842564684005515c9e;
        address swapVerifierAddress = 0xae26485ACDDeFd486Fe9ad7C2b34169d360737c7;
        address evcAddress = 0x0C9a3dd6b8F28529d72d7f9cE918D493519EE383;

        address deployer = vm.addr(deployerPrivateKey);
        vm.startBroadcast(deployerPrivateKey);

        Liquidator liquidator = new Liquidator(deployer, swapperAddress, swapVerifierAddress, evcAddress);

        console2.log("Liquidator deployed at: ", address(liquidator));
    }
}
