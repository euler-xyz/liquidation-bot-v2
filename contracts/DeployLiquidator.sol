// SPDX-License-Identifier: MIT

pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";

import {Liquidator} from "./Liquidator.sol";

import "forge-std/console2.sol";

contract DeployLiquidator is Script {
    function run() public {
        uint256 deployerPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");

        address swapperAddress = 0x697Ca30D765c1603890D88AAffBa3BeCCe72059d;
        address swapVerifierAddress = 0x296041DbdBC92171293F23c0a31e1574b791060d;
        address evcAddress = 0x59f0FeEc4fA474Ad4ffC357cC8d8595B68abE47d;
        address pyth = 0x4305FB66699C3B2702D4d05CF36551390A4c69C6;

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
