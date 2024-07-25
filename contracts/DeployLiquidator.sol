pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";

import {Liquidator} from "./Liquidator.sol";

import "forge-std/console2.sol";

contract DeployLiquidator is Script {

    function run() public {

        address deployer = address(this);

        uint256 deployerPrivateKey = vm.deriveKey(vm.envString("MNEMONIC"), 0);
        
        // address swapperAddress = vm.envAddress("SWAPPER_ADDRESS");
        // address swapVerifierAddress = vm.envAddress("SWAP_VERIFIER_ADDRESS");
        // address evcAddress = vm.envAddress("EVC_ADDRESS");

        address swapperAddress = 0xfA898de6CcE1715a14F579c316C6cfd7F869655B;
        address swapVerifierAddress = 0x4c0bF4C73f2Cf53259C84694b2F26Adc4916921e;
        address evcAddress = 0xB8d6D6b01bFe81784BE46e5771eF017Fa3c906d8;

        deployer = vm.addr(deployerPrivateKey);
        vm.startBroadcast(deployerPrivateKey);

        Liquidator liquidator = new Liquidator(swapperAddress, swapVerifierAddress, evcAddress);

        console2.log("Liquidator deployed at: ", address(liquidator));
    }
}