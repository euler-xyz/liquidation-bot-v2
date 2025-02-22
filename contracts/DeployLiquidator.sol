// SPDX-License-Identifier: MIT

pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";

import {Liquidator} from "./Liquidator.sol";

import "forge-std/console2.sol";

contract DeployLiquidator is Script {
    function run() public {
        uint256 deployerPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");

        address swapperAddress = 0xbAf5B12c92711a3657DD4adA6b3C7801e83Bb56a;
        address swapVerifierAddress = 0x003ef4048b45a5A79D4499aaBd52108B3Bc9209f;
        address evcAddress = 0x4860C903f6Ad709c3eDA46D3D502943f184D4315;
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
