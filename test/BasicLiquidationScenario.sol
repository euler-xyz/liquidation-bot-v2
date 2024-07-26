// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {Script} from "forge-std/Script.sol";

import {IEVault} from "../contracts/IEVault.sol";
import {IEVC} from "../contracts/IEVC.sol";
import {IERC20} from "../contracts/IEVault.sol";

import {MockPriceOracle} from "../contracts/MockPriceOracle.sol";

contract BasicScenario is Test, Script {
    address constant TEST_VAULT_1_ADDRESS = 0x6a90D73D17bf8d3DD5f5924fc0d5D9e8af23042d;
    address constant TEST_VAULT_1_UNDERLYING = 0x6B175474E89094C44Da98b954EedeAC495271d0F;
    
    address constant TEST_VAULT_2_ADDRESS = 0xD814CdD8Ca70135E1406fFC0e3EcaB1aed5b070c;
    address constant TEST_VAULT_2_UNDERLYING = 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984;

    address constant ORACLE_ADDRESS = 0x221416CFa5A3CD92035E537ded1dD12d4d587c03;

    address constant EVC_ADDRESS = 0xB8d6D6b01bFe81784BE46e5771eF017Fa3c906d8;
    
    address deployer;
    address borrower;
    address liquidator;

    IEVault vault1;
    IEVault vault2;

    IERC20 underlying1;
    IERC20 underlying2;

    MockPriceOracle oracle;

    IEVC evc;

    function run() public {
        evc = IEVC(EVC_ADDRESS);

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
        
        console.log("Initial state:");
        logState();

        // distributeTokens();

        // console.log("After distributing tokens:");
        // logState();

        // depositInVaults();
        
        // console.log("After depositing in vaults:");
        // logState();

        // vault1.setLTV(address(vault2), 0.9e4, 0.9e4, 0);

        // oracle.setPrice(TEST_VAULT_1_UNDERLYING, address(0), 1e18);
        // oracle.setPrice(TEST_VAULT_2_UNDERLYING, address(0), 1e18);
        // oracle.setPrice(TEST_VAULT_1_ADDRESS, address(0), 1e18);
        // oracle.setPrice(TEST_VAULT_2_ADDRESS, address(0), 1e18);

        // vm.stopBroadcast();

        // vm.startBroadcast(borrowerPrivateKey);

        // underlying2.approve(address(vault2), type(uint).max);
        // vault2.deposit(1e10, borrower);
        
        // console.log("After borrower deposit in vauls:");
        // logState();

        // evc.enableCollateral(borrower, address(vault2));
        // evc.enableController(borrower, address(vault1));

        // vault1.borrow(5e9, borrower);
        // console.log("After borrower borrow:");
        // logState();

        // vault1.borrow(1e9, borrower);
        // console.log("After borrowing a little bit more:");
        // logState();

        // vm.stopBroadcast();

        // vm.startBroadcast(deployerPrivateKey);
        // vault1.setLTV(address(vault2), 0.2e4, 0.2e4, 0);
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
        console.log("Account States:");
        console.log("Deployer:");
        console.log("Vault 1 balance: ", vault1.balanceOf(deployer));
        console.log("Underlying 1 balance: ", underlying1.balanceOf(deployer));
        console.log("Vault 2 balance: ", vault2.balanceOf(deployer));
        console.log("Underlying 2 balance: ", underlying2.balanceOf(deployer));
        console.log("--------------------");
        console.log("Borrower:");
        console.log("Vault 1 balance: ", vault1.balanceOf(borrower));
        console.log("Underlying 1 balance: ", underlying1.balanceOf(borrower));
        console.log("Vault 2 balance: ", vault2.balanceOf(borrower));
        console.log("Underlying 2 balance: ", underlying2.balanceOf(borrower));
        console.log("--------------------");
        console.log("Liquidator:");
        console.log("Vault 1 balance: ", vault1.balanceOf(liquidator));
        console.log("Underlying 1 balance: ", underlying1.balanceOf(liquidator));
        console.log("Vault 2 balance: ", vault2.balanceOf(liquidator));
        console.log("Underlying 2 balance: ", underlying2.balanceOf(liquidator));
        console.log("----------------------------------------");
        console.log(" ");
        console.log("Vault States:");
        console.log("Vault 1:");
        console.log("Total Supply: ", vault1.totalSupply());
        console.log("Total Assets: ", vault1.totalAssets());
        console.log("Total Borrow: ", vault1.totalBorrows());
        console.log("--------------------");
        console.log("Vault 2:");
        console.log("Total Supply: ", vault2.totalSupply());
        console.log("Total Assets: ", vault2.totalAssets());
        console.log("Total Borrow: ", vault2.totalBorrows());
        console.log("----------------------------------------");
    }
}