pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";

import {Liquidator} from "./Liquidator.sol";

import "forge-std/console2.sol";

contract DeployLiquidator is Script {

    function run() public {

        address deployer = address(this);

        // uint256 deployerPrivateKey = vm.deriveKey(vm.envString("MNEMONIC"), 0);
        uint256 deployerPrivateKey =vm.envUint("EOA_PRIVATE_KEY");
        
        // address swapperAddress = vm.envAddress("SWAPPER_ADDRESS");
        // address swapVerifierAddress = vm.envAddress("SWAP_VERIFIER_ADDRESS");
        // address evcAddress = vm.envAddress("EVC_ADDRESS");

        address swapperAddress = 0xf2FE32e706c849E7b049AC7B75F82E98225969d7;
        address swapVerifierAddress = 0x3f2d64E717A74B564664B2e7B237f3AD42D76D5A;
        address evcAddress = 0xc860d644A514d0626c8B87ACFA63fE12644Ce3cd;

        deployer = vm.addr(deployerPrivateKey);
        vm.startBroadcast(deployerPrivateKey);

        Liquidator liquidator = new Liquidator(swapperAddress, swapVerifierAddress, evcAddress);

        console2.log("Liquidator deployed at: ", address(liquidator));
    }
}