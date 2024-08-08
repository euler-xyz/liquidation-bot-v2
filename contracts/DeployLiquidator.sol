// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Test} from "forge-std/Test.sol";

import {Liquidator} from "./Liquidator.sol";

import "forge-std/console2.sol";

contract DeployLiquidator is Script {
    function run() public {
        uint256 deployerPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");

        address swapperAddress = 0xf11A61f808526B45ba797777Ab7B1DB5CC65DE0F;
        address swapVerifierAddress = 0x8aAA2CaEca30AB50d48EB0EA71b83c49A2f49791;
        address evcAddress = 0xE45Ee4046bD755330D555dFe4aDA7839a3eEb926;

        address deployer = vm.addr(deployerPrivateKey);
        vm.startBroadcast(deployerPrivateKey);

        Liquidator liquidator = new Liquidator(deployer, swapperAddress, swapVerifierAddress, evcAddress);

        console2.log("Liquidator deployed at: ", address(liquidator));
    }
}
