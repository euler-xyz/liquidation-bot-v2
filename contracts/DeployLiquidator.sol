pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";

import {Liquidator} from "./Liquidator.sol";

import "forge-std/console2.sol";

contract DeployLiquidator is Script {

    function run() public {

        address deployer = address(this);

        uint256 deployerPrivateKey = vm.deriveKey(vm.envString("MNEMONIC"), 0);
        
        address swapperAddress = vm.envAddress("SWAPPER_ADDRESS");
        address swapVerifierAddress = vm.envAddress("SWAP_VERIFIER_ADDRESS");
        address evcAddress = vm.envAddress("EVC_ADDRESS");

        deployer = vm.addr(deployerPrivateKey);
        vm.startBroadcast(deployerPrivateKey);

        Liquidator liquidator = new Liquidator(swapperAddress, swapVerifierAddress, evcAddress);

        console2.log("Liquidator deployed at: ", address(liquidator));
    }
}