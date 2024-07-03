// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.0;

import {Test, console} from "forge-std/Test.sol";
import {Script} from "forge-std/Script.sol";

import {IEVault} from "../contracts/IEVault.sol";
import {IEVC} from "../contracts/IEVC.sol";
import {IERC20} from "../contracts/IEVault.sol";

import {MockPriceOracle} from "../contracts/MockPriceOracle.sol";
import {GenericFactory} from "../contracts/GenericFactory/GenericFactory.sol";

contract BasicScenario is Test, Script {
    address constant TEST_VAULT_1_ADDRESS = 0xf6cb30F1b333B511be23f6Fc0b733ed26030d6f7;
    address constant TEST_VAULT_1_UNDERLYING = 0x6B175474E89094C44Da98b954EedeAC495271d0F;
    address constant TEST_VAULT_2_ADDRESS = 0x10F9509d401dedb0605616B89cfE26FA614084B7;
    address constant TEST_VAULT_2_UNDERLYING = 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984;
    address constant ORACLE_ADDRESS = 0x0C8542AB89c1C60D711B00F309f7EF63b5D9d6eb;
    address constant FACTORY_ADDRESS = 0x6c383Ef7C9Bf496b5c847530eb9c49a3ED6E4C56;

    string constant MNEMONIC = "test test test test test test test test test test test junk";
    
    address deployer;

    IEVault vault1;
    IEVault vault2;

    IERC20 underlying1;
    IERC20 underlying2;

    GenericFactory factory;

    MockPriceOracle oracle;

    function run() public {
        vault1 = IEVault(TEST_VAULT_1_ADDRESS);
        underlying1 = IERC20(TEST_VAULT_1_UNDERLYING);
        
        vault2 = IEVault(TEST_VAULT_2_ADDRESS);
        underlying2 = IERC20(TEST_VAULT_2_UNDERLYING);

        oracle = MockPriceOracle(ORACLE_ADDRESS);

        factory = GenericFactory(FACTORY_ADDRESS);

        uint256 deployerPrivateKey = vm.deriveKey(MNEMONIC, 0);
        deployer = vm.addr(deployerPrivateKey);

        vm.startBroadcast(deployerPrivateKey);

        console.log("underlying1 balance: ", underlying1.balanceOf(deployer));
        console.log("underlying2 balance: ", underlying2.balanceOf(deployer));

        console.log("msg sender: ", msg.sender);
        console.log("sender balance: ", underlying1.balanceOf(msg.sender));

        underlying1.approve(address(vault1), type(uint).max);
        underlying2.approve(address(vault2), type(uint).max);

        // IEVault vault = IEVault(
        //     factory.createProxy(address(0), true, abi.encodePacked(address(underlying1), address(oracle), address(1)))
        // );

        // console.log(vault1.asset());
        console.log(underlying1.name());

        // vault1.setLTV(address(vault2), 0.9e4, 0.9e4, 0);
    }
}