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

        address swapperAddress = 0xf4e55515952BdAb2aeB4010f777E802D61eB384f;
        address swapVerifierAddress = 0xe519389F8c262d4301Fd2830196FB7D0021daf59;
        address evcAddress = 0x72F853E9E202600c5017B5A060168603c3ed7368;

        deployer = vm.addr(deployerPrivateKey);
        vm.startBroadcast(deployerPrivateKey);

        Liquidator liquidator = new Liquidator(swapperAddress, swapVerifierAddress, evcAddress);

        console2.log("Liquidator deployed at: ", address(liquidator));
    }
}