// SPDX-License-Identifier: MIT

pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";

import {Liquidator} from "./Liquidator.sol";

import "forge-std/console2.sol";

contract DeployLiquidator is Script {
    function run() public {
        uint256 deployerPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");

        address swapperAddress = 0x319E8ecd3BaB57fE684ca1aCfaB60c5603087B3A;
        address swapVerifierAddress = 0x7eaf8C22480129E5D7426e3A33880D7bE19B50a7;
        address evcAddress = 0x2A1176964F5D7caE5406B627Bf6166664FE83c60;
        address pyth = 0x2880aB155794e7179c9eE2e38200202908C17B43;

        address deployer = vm.addr(deployerPrivateKey);
        vm.startBroadcast(deployerPrivateKey);
        
        uint256 beforeGas = gasleft();
        console2.log("Gas before: ", beforeGas);
        console2.log("Gas price: ", tx.gasprice);

        Liquidator liquidator = new Liquidator(deployer, swapperAddress, swapVerifierAddress, evcAddress, pyth);
        uint256 afterGas = gasleft();
        console2.log("Gas after: ", afterGas);

        console2.log("Total gas cost: ", (beforeGas - afterGas) * tx.gasprice);

        console2.log("Liquidator deployed at: ", address(liquidator));
    }
}
