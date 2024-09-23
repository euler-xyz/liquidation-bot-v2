// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {Script} from "forge-std/Script.sol";

import {IEVault} from "../contracts/IEVault.sol";
import {IEVC} from "../contracts/IEVC.sol";
import {IERC20} from "../contracts/IEVault.sol";

import {MockPriceOracle} from "../contracts/MockPriceOracle.sol";

contract LiquidationSetup is Test, Script {
    address constant USDC_VAULT = 0x577e289F663A4E29c231135c09d6a0713ce7AAff;
    address constant USDC = 0xaf88d065e77c8cC2239327C5EDb3A432268e5831;

    address constant DAI_VAULT = 0xF67F9B1042A7f419c2C0259C983FB1f75f981fD4;
    address constant DAI = 0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1;

    address constant EVC_ADDRESS = 0xE45Ee4046bD755330D555dFe4aDA7839a3eEb926;
    address constant LIQUIDATOR_CONTRACT_ADDRESS = 0xA8A46596a7B17542d2cf6993FC61Ea0CBb4474c1;
    
    address constant profitReceiver = 0x140556939f9Cfa711078DeFBb01B3e51A53Bc464;

    address depositor;
    uint256 depositorPrivateKey;
    address borrower;
    uint256 borrowerPrivateKey;
    address liquidator;
    uint256 liquidatorPrivateKey;

    IEVault usdc_vault;
    IEVault dai_vault;

    IERC20 usdc;
    IERC20 dai;

    IEVC evc;

    function run() public {
        evc = IEVC(EVC_ADDRESS);

        usdc_vault = IEVault(USDC_VAULT);
        usdc = IERC20(USDC);

        dai_vault = IEVault(DAI_VAULT);
        dai = IERC20(DAI);

        depositorPrivateKey = vm.envUint("DEPOSITOR_PRIVATE_KEY");
        depositor = vm.addr(depositorPrivateKey);

        borrowerPrivateKey = vm.envUint("BORROWER_PRIVATE_KEY");
        borrower = vm.addr(borrowerPrivateKey);

        liquidatorPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");
        liquidator = vm.addr(liquidatorPrivateKey);

        console.log("Current state:");
        logState();

        // depositorDepositInVaults();
        // console.log("After depositing in vaults:");
        // logState();

        // borrowerDepositAndEnableCollateralAndController();
        // console.log("After borrower deposit in vaults:");
        // logState();

        // borrowerBorrowUSDC();
        // console.log("After borrower borrow:");
        // logState();

        // depositorDepositAndTransferToLiquidatorContract();
        // console.log("After depositor deposit in liquidator contract:");
        // logState();
    }

    function depositorDepositInVaults() internal {
        vm.startBroadcast(depositorPrivateKey);

        usdc.approve(address(usdc_vault), type(uint256).max);
        dai.approve(address(dai_vault), type(uint256).max);

        usdc_vault.deposit(1e6, depositor);
        dai_vault.deposit(1e18, depositor);

        vm.stopBroadcast();
    }

    function borrowerDepositAndEnableCollateralAndController() internal {
        vm.startBroadcast(borrowerPrivateKey);

        dai.approve(address(dai_vault), type(uint256).max);
        dai_vault.deposit(1e18, borrower);

        evc.enableCollateral(borrower, address(dai_vault));
        evc.enableController(borrower, address(usdc_vault));

        vm.stopBroadcast();
    }

    function borrowerBorrowUSDC() internal {
        vm.startBroadcast(borrowerPrivateKey);

        usdc_vault.borrow(5e5, borrower);

        vm.stopBroadcast();
    }

    function depositorDepositAndTransferToLiquidatorContract() internal {
        vm.startBroadcast(depositorPrivateKey);
        usdc_vault.deposit(1e6, LIQUIDATOR_CONTRACT_ADDRESS);
        dai_vault.deposit(1e18, LIQUIDATOR_CONTRACT_ADDRESS);
        vm.stopBroadcast();
    }

    function logState() internal view {
        console.log("Account States:");
        console.log("Depositor: ", depositor);
        console.log("USDC Vault balance: ", usdc_vault.balanceOf(depositor));
        console.log("USDC balance: ", usdc.balanceOf(depositor));
        console.log("DAI Vault balance: ", dai_vault.balanceOf(depositor));
        console.log("DAI balance: ", dai.balanceOf(depositor));
        console.log("--------------------");
        console.log("Borrower: ", borrower);
        console.log("USDC Vault balance: ", usdc_vault.balanceOf(borrower));
        console.log("USDC borrow: ", usdc_vault.debtOf(borrower));
        console.log("USDC balance: ", usdc.balanceOf(borrower));
        console.log("DAI Vault balance: ", dai_vault.balanceOf(borrower));
        console.log("DAI borrow: ", dai_vault.debtOf(borrower));
        console.log("DAI balance: ", dai.balanceOf(borrower));
        console.log("--------------------");
        console.log("Liquidator: ", liquidator);
        console.log("USDC Vault balance: ", usdc_vault.balanceOf(liquidator));
        console.log("USDC balance: ", usdc.balanceOf(liquidator));
        console.log("DAI Vault balance: ", dai_vault.balanceOf(liquidator));
        console.log("DAI balance: ", dai.balanceOf(liquidator));
        console.log("--------------------");
        console.log("Profit Receiver: ", profitReceiver);
        console.log("USDC Vault balance: ", usdc_vault.balanceOf(profitReceiver));
        console.log("USDC balance: ", usdc.balanceOf(profitReceiver));
        console.log("DAI Vault balance: ", dai_vault.balanceOf(profitReceiver));
        console.log("DAI balance: ", dai.balanceOf(profitReceiver));
        console.log("--------------------");
        console.log("Liquidator Contract: ", LIQUIDATOR_CONTRACT_ADDRESS);
        console.log("USDC Vault balance: ", usdc_vault.balanceOf(LIQUIDATOR_CONTRACT_ADDRESS));
        console.log("USDC borrow: ", usdc_vault.debtOf(LIQUIDATOR_CONTRACT_ADDRESS));
        console.log("USDC balance: ", usdc.balanceOf(LIQUIDATOR_CONTRACT_ADDRESS));
        console.log("DAI Vault balance: ", dai_vault.balanceOf(LIQUIDATOR_CONTRACT_ADDRESS));
        console.log("DAI borrow: ", dai_vault.debtOf(LIQUIDATOR_CONTRACT_ADDRESS));
        console.log("DAI balance: ", dai.balanceOf(LIQUIDATOR_CONTRACT_ADDRESS));
        console.log("----------------------------------------");
        console.log(" ");
        console.log("Vault States:");
        console.log("USDC Vault:");
        console.log("Total Supply: ", usdc_vault.totalSupply());
        console.log("Total Assets: ", usdc_vault.totalAssets());
        console.log("Total Borrow: ", usdc_vault.totalBorrows());
        console.log("--------------------");
        console.log("DAI Vault:");
        console.log("Total Supply: ", dai_vault.totalSupply());
        console.log("Total Assets: ", dai_vault.totalAssets());
        console.log("Total Borrow: ", dai_vault.totalBorrows());
        console.log("----------------------------------------");
    }
}
