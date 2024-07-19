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
    address constant TEST_VAULT_1_ADDRESS = 0x21657b967dFae90c6a1ec51D7cfa659B95291F6f;
    address constant TEST_VAULT_1_UNDERLYING = 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48;
    
    address constant TEST_VAULT_2_ADDRESS = 0xDb17C6bBD90D09011FB8B8F83E98d906371D1930;
    address constant TEST_VAULT_2_UNDERLYING = 0x6B175474E89094C44Da98b954EedeAC495271d0F;

    address constant ORACLE_ADDRESS = 0xE57A305f34fD0B6A55A66e8ec9559e6573100cBe;
    
    address deployer;
    address borrower;
    address liquidator;

    IEVault vault1;
    IEVault vault2;

    IERC20 underlying1;
    IERC20 underlying2;

    MockPriceOracle oracle;

    function run() public {
        vault1 = IEVault(TEST_VAULT_1_ADDRESS);
        underlying1 = IERC20(TEST_VAULT_1_UNDERLYING);
        
        vault2 = IEVault(TEST_VAULT_2_ADDRESS);
        underlying2 = IERC20(TEST_VAULT_2_UNDERLYING);

        oracle = MockPriceOracle(ORACLE_ADDRESS);

        uint256 deployerPrivateKey = vm.deriveKey(vm.envString("MNEMONIC"), 0);
        
        deployer = vm.addr(deployerPrivateKey);

        vm.startBroadcast(deployerPrivateKey);


        uint256 liquidatorPrivateKey = vm.deriveKey(vm.envString("MNEMONIC"), 1);
        liquidator = vm.addr(liquidatorPrivateKey);

        uint256 borrowerPrivateKey = vm.deriveKey(vm.envString("MNEMONIC"), 2);
        borrower = vm.addr(borrowerPrivateKey);

        // console.log("deployer public key: ", deployer);
        // console.log("liquidator: ", liquidator);
        // console.log("borrower: ", borrower);
        
        console.log("Initial state:");
        logState();

        distributeTokens();

        console.log("After distributing tokens:");
        logState();

        console.log("Vault1 code length", TEST_VAULT_1_ADDRESS.code.length);
        console.log("Vault2 code length", TEST_VAULT_2_ADDRESS.code.length);

        console.log(vault1.asset());
        // depositInVaults();
        
        // console.log("After depositing in vaults:");
        // logState();
        
        // underlying1.transfer(borrower, 1e10);
        // underlying2.approve(address(vault2), type(uint).max);

        // IEVault vault = IEVault(
        //     factory.createProxy(address(0), true, abi.encodePacked(address(underlying1), address(oracle), address(1)))
        // );

        // console.log(vault1.asset());
        // console.log(underlying1.name());

        // vault1.setLTV(address(vault2), 0.9e4, 0.9e4, 0);
    }

    function depositInVaults() internal {
        underlying1.approve(address(vault1), type(uint).max);
        underlying2.approve(address(vault2), type(uint).max);

        vault1.deposit(1e10, msg.sender);
        vault2.deposit(1e10, msg.sender);
    }

    function distributeTokens() internal {
        underlying1.transfer(borrower, 1e10);
        underlying2.transfer(borrower, 1e10);
    }

    function logState() internal {
        console.log(" ");
        console.log("Deployer:");
        // console.log("Vault 1 balance: ", vault1.balanceOf(deployer));
        console.log("Underlying 1 balance: ", underlying1.balanceOf(deployer));
        // console.log("Vault 2 balance: ", vault2.balanceOf(deployer));
        console.log("Underlying 2 balance: ", underlying2.balanceOf(deployer));
        console.log("--------------------");
        console.log("Borrower:");
        // console.log("Vault 1 balance: ", vault1.balanceOf(borrower));
        console.log("Underlying 1 balance: ", underlying1.balanceOf(borrower));
        // console.log("Vault 2 balance: ", vault2.balanceOf(borrower));
        console.log("Underlying 2 balance: ", underlying2.balanceOf(borrower));
        console.log("--------------------");
        console.log("Liquidator:");
        // console.log("Vault 1 balance: ", vault1.balanceOf(liquidator));
        console.log("Underlying 1 balance: ", underlying1.balanceOf(liquidator));
        // console.log("Vault 2 balance: ", vault2.balanceOf(liquidator));
        console.log("Underlying 2 balance: ", underlying2.balanceOf(liquidator));
        console.log("----------------------------------------");
    }
}